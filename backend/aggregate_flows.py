"""Aggregate OA-21229 station OD files into dense station-by-5-minute rows."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
from pathlib import Path
import re
import sqlite3
from typing import Iterator
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "inventory" / "inventory.sqlite3"
DEFAULT_RAW = ROOT / "data" / "station_flow" / "raw"
DATASET_ID = "OA-21229"
KST_SUFFIX = "+09:00"
REQUIRED_COLUMNS = {
    "기준_날짜",
    "집계_기준",
    "기준_시간대",
    "시작_대여소_ID",
    "시작_대여소명",
    "종료_대여소_ID",
    "종료_대여소명",
    "전체_건수",
}


class FlowImportError(RuntimeError):
    """Raised when a raw flow file cannot be safely normalized."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    ensure_schema(db)
    return db


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS station_master (
          station_id TEXT PRIMARY KEY,
          station_name TEXT NOT NULL,
          capacity INTEGER,
          latitude REAL,
          longitude REAL,
          source TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flow_imports (
          source_file TEXT PRIMARY KEY,
          dataset_id TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          imported_at TEXT NOT NULL,
          source_rows INTEGER NOT NULL,
          dense_rows INTEGER NOT NULL,
          station_days INTEGER NOT NULL,
          min_date TEXT NOT NULL,
          max_date TEXT NOT NULL,
          source_priority INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flows_5m (
          station_id TEXT NOT NULL,
          service_date TEXT NOT NULL,
          minute_of_day INTEGER NOT NULL CHECK(minute_of_day BETWEEN 0 AND 1435),
          interval_start TEXT NOT NULL,
          rentals INTEGER NOT NULL CHECK(rentals >= 0),
          returns INTEGER NOT NULL CHECK(returns >= 0),
          source_file TEXT NOT NULL,
          source_priority INTEGER NOT NULL,
          imported_at TEXT NOT NULL,
          PRIMARY KEY(station_id, service_date, minute_of_day)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_flows_5m_interval
          ON flows_5m(interval_start);
        CREATE INDEX IF NOT EXISTS idx_flows_5m_source
          ON flows_5m(source_file);
        DROP VIEW IF EXISTS station_flows_5m;
        CREATE VIEW station_flows_5m AS
          SELECT f.station_id, m.station_name, m.capacity, m.latitude, m.longitude,
                 f.service_date, f.minute_of_day, f.interval_start,
                 f.rentals, f.returns, f.source_file
          FROM flows_5m f
          LEFT JOIN station_master m ON m.station_id = f.station_id;
        """
    )


def _open_csv(archive: zipfile.ZipFile) -> tuple[io.TextIOWrapper, str]:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) != 1 or Path(members[0].filename).suffix.lower() != ".csv":
        raise FlowImportError("OA-21229 ZIP must contain exactly one CSV file")
    member = members[0]
    if Path(member.filename).name != member.filename:
        raise FlowImportError(f"unsafe ZIP member path: {member.filename!r}")
    with archive.open(member) as sample_stream:
        sample = sample_stream.read(4096)
    encoding = "utf-8-sig"
    try:
        sample.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp949"
    stream = io.TextIOWrapper(archive.open(member), encoding=encoding, newline="")
    return stream, encoding


def _parse_day(value: str) -> str:
    try:
        return datetime.strptime(value.strip(), "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise FlowImportError(f"invalid 기준_날짜: {value!r}") from exc


def _parse_minute(value: str) -> int:
    value = value.strip().zfill(4)
    if not re.fullmatch(r"\d{4}", value):
        raise FlowImportError(f"invalid 기준_시간대: {value!r}")
    hour, minute = int(value[:2]), int(value[2:])
    if hour > 23 or minute > 59 or minute % 5:
        raise FlowImportError(f"invalid 5-minute time: {value!r}")
    return hour * 60 + minute


def _parse_count(value: str) -> int:
    try:
        count = int(value.strip())
    except ValueError as exc:
        raise FlowImportError(f"invalid 전체_건수: {value!r}") from exc
    if count < 0:
        raise FlowImportError(f"negative 전체_건수: {value!r}")
    return count


def _interval_start(day: str, minute: int) -> str:
    return f"{day}T{minute // 60:02d}:{minute % 60:02d}:00{KST_SUFFIX}"


def _source_priority(filename: str) -> int:
    if re.search(r"_20\d{6}\.zip$", filename, re.IGNORECASE):
        return 2
    return 1


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        while chunk := file.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(rows: Iterator[tuple], size: int = 10_000) -> Iterator[list[tuple]]:
    batch: list[tuple] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def sync_station_master(db: sqlite3.Connection) -> int:
    """Refresh the master from the latest successful real-time inventory view."""
    exists = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='latest_inventory'"
    ).fetchone()
    if not exists:
        return 0
    timestamp = utcnow()
    rows = db.execute(
        "SELECT station_id, name, rack_count, latitude, longitude FROM latest_inventory"
    ).fetchall()
    db.executemany(
        """
        INSERT INTO station_master(
          station_id, station_name, capacity, latitude, longitude, source, updated_at
        ) VALUES(?,?,?,?,?,'realtime-inventory',?)
        ON CONFLICT(station_id) DO UPDATE SET
          station_name=excluded.station_name,
          capacity=excluded.capacity,
          latitude=excluded.latitude,
          longitude=excluded.longitude,
          source=excluded.source,
          updated_at=excluded.updated_at
        """,
        [(*row, timestamp) for row in rows],
    )
    return len(rows)


def import_flow_zip(
    path: Path,
    db: sqlite3.Connection,
    *,
    force: bool = False,
) -> dict[str, int | str]:
    path = path.resolve()
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise FlowImportError(f"not a valid ZIP file: {path}")
    source_file = path.name
    if db.execute("SELECT 1 FROM flow_imports WHERE source_file=?", (source_file,)).fetchone():
        if not force:
            return {"sourceFile": source_file, "status": "skipped"}

    file_hash = _file_sha256(path)
    priority = _source_priority(source_file)
    imported_at = utcnow()
    source_rows = dense_rows = station_days = 0
    completed_days: set[str] = set()
    min_date: str | None = None
    max_date: str | None = None
    current_day: str | None = None
    flows: dict[tuple[str, int], list[int]] = {}
    names: dict[str, str] = {}

    def flush_day() -> None:
        nonlocal dense_rows, station_days
        if current_day is None:
            return
        timestamp = imported_at
        db.executemany(
            """
            INSERT INTO station_master(
              station_id, station_name, capacity, latitude, longitude, source, updated_at
            ) VALUES(?,?,NULL,NULL,NULL,'oa-21229',?)
            ON CONFLICT(station_id) DO NOTHING
            """,
            [(station_id, name or station_id, timestamp) for station_id, name in names.items()],
        )

        def dense() -> Iterator[tuple]:
            for station_id in sorted(names):
                for minute in range(0, 1440, 5):
                    rentals, returns = flows.get((station_id, minute), (0, 0))
                    yield (
                        station_id,
                        current_day,
                        minute,
                        _interval_start(current_day, minute),
                        rentals,
                        returns,
                        source_file,
                        priority,
                        timestamp,
                    )

        sql = """
            INSERT INTO flows_5m(
              station_id, service_date, minute_of_day, interval_start,
              rentals, returns, source_file, source_priority, imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(station_id, service_date, minute_of_day) DO UPDATE SET
              interval_start=excluded.interval_start,
              rentals=excluded.rentals,
              returns=excluded.returns,
              source_file=excluded.source_file,
              source_priority=excluded.source_priority,
              imported_at=excluded.imported_at
            WHERE excluded.source_priority >= flows_5m.source_priority
        """
        for batch in _chunks(dense()):
            db.executemany(sql, batch)
            dense_rows += len(batch)
        station_days += len(names)

    db.commit()
    try:
        db.execute("BEGIN IMMEDIATE")
        if force:
            db.execute("DELETE FROM flows_5m WHERE source_file=?", (source_file,))
            db.execute("DELETE FROM flow_imports WHERE source_file=?", (source_file,))
        with zipfile.ZipFile(path) as archive:
            stream, _encoding = _open_csv(archive)
            with stream:
                reader = csv.DictReader(stream)
                columns = set(reader.fieldnames or [])
                missing = REQUIRED_COLUMNS - columns
                if missing:
                    raise FlowImportError(f"missing CSV columns: {sorted(missing)}")
                for row in reader:
                    source_rows += 1
                    day = _parse_day(row["기준_날짜"])
                    if current_day is None:
                        current_day = day
                    elif day != current_day:
                        flush_day()
                        completed_days.add(current_day)
                        if day in completed_days:
                            raise FlowImportError("CSV dates are not grouped contiguously")
                        current_day = day
                        flows = {}
                        names = {}
                    min_date = day if min_date is None else min(min_date, day)
                    max_date = day if max_date is None else max(max_date, day)
                    minute = _parse_minute(row["기준_시간대"])
                    count = _parse_count(row["전체_건수"])
                    criterion = row["집계_기준"].strip()
                    if criterion == "출발시간":
                        station_id = row["시작_대여소_ID"].strip()
                        station_name = row["시작_대여소명"].strip()
                        index = 0
                    elif criterion == "도착시간":
                        station_id = row["종료_대여소_ID"].strip()
                        station_name = row["종료_대여소명"].strip()
                        index = 1
                    else:
                        raise FlowImportError(f"unknown 집계_기준: {criterion!r}")
                    if not station_id:
                        raise FlowImportError("empty station ID")
                    names.setdefault(station_id, station_name or station_id)
                    values = flows.setdefault((station_id, minute), [0, 0])
                    values[index] += count
                flush_day()

        if not source_rows or min_date is None or max_date is None:
            raise FlowImportError("CSV contains no data rows")
        master_rows = sync_station_master(db)
        db.execute(
            "INSERT INTO flow_imports VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                source_file,
                DATASET_ID,
                file_hash,
                imported_at,
                source_rows,
                dense_rows,
                station_days,
                min_date,
                max_date,
                priority,
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "sourceFile": source_file,
        "status": "imported",
        "sourceRows": source_rows,
        "denseRows": dense_rows,
        "stationDays": station_days,
        "masterRows": master_rows,
        "minDate": min_date,
        "maxDate": max_date,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import OA-21229 ZIP files into SQLite.")
    parser.add_argument("paths", nargs="*", type=Path, help="ZIP files; defaults to raw/*.zip")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true", help="rebuild files already imported")
    parser.add_argument("--sync-master-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with connect(args.db) as db:
        if args.sync_master_only:
            print(f"station_master synced: {sync_station_master(db):,} rows")
            return 0
        paths = args.paths or sorted(DEFAULT_RAW.glob("*.zip"))
        if not paths:
            raise SystemExit(f"no ZIP files found under {DEFAULT_RAW}")
        for path in paths:
            result = import_flow_zip(path, db, force=args.force)
            print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
