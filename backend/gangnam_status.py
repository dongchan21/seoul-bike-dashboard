"""Fast status and source-date quality report for the Gangnam training DB."""

from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
import zipfile

from backend.aggregate_flows import _csv_members, _open_csv
from backend.download_station_flow import DEFAULT_OUTPUT as DEFAULT_RAW
from backend.prepare_gangnam_year import DEFAULT_DB, END_DATE, START_DATE


def archive_dates(raw_dir: Path) -> tuple[set[str], list[str], list[dict[str, str]]]:
    dates: set[str] = set()
    empty_members: list[str] = []
    mismatches: list[dict[str, str]] = []
    for path in raw_dir.glob("tpss_bcycl_od_statnhm_*.zip"):
        with zipfile.ZipFile(path) as archive:
            for member in _csv_members(archive):
                stream, _encoding = _open_csv(archive, member)
                with stream:
                    reader = csv.reader(stream)
                    header = next(reader, None)
                    row = next(reader, None)
                if not header or not row:
                    empty_members.append(member.filename)
                    continue
                try:
                    value = row[header.index("기준_날짜")].strip()
                except (ValueError, IndexError):
                    empty_members.append(member.filename)
                    continue
                actual = f"{value[:4]}-{value[4:6]}-{value[6:]}"
                dates.add(actual)
                match = re.search(r"(20\d{6})\.csv$", member.filename)
                if match and match.group(1) != value:
                    expected = match.group(1)
                    mismatches.append(
                        {
                            "member": member.filename,
                            "filenameDate": f"{expected[:4]}-{expected[4:6]}-{expected[6:]}",
                            "dataDate": actual,
                        }
                    )
    return dates, empty_members, mismatches


def expected_dates(start: str, end: str) -> set[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return {(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show Gangnam dataset status without a full scan.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = sqlite3.connect(args.db)
    imports = db.execute(
        """SELECT count(*), sum(source_rows), sum(accepted_rows), sum(dense_rows),
                  sum(station_days), min(min_date), max(max_date)
           FROM flow_imports"""
    ).fetchone()
    stations = db.execute(
        "SELECT count(*), sum(CASE WHEN district='강남구' THEN 1 ELSE 0 END) FROM station_master"
    ).fetchone()
    model = db.execute(
        """SELECT model_version, training_start, training_end, training_rows, station_count
           FROM baseline_models ORDER BY trained_at DESC LIMIT 1"""
    ).fetchone()
    baseline_rows = db.execute("SELECT count(*) FROM baseline_5m").fetchone()[0]
    db.close()
    available, empty_members, mismatches = archive_dates(args.raw_dir)
    expected = expected_dates(START_DATE, END_DATE)
    report = {
        "db": str(args.db.resolve()),
        "dbBytes": args.db.stat().st_size,
        "imports": {
            "files": imports[0],
            "sourceRows": imports[1],
            "acceptedRows": imports[2],
            "denseRows": imports[3],
            "stationDays": imports[4],
            "minDate": imports[5],
            "maxDate": imports[6],
        },
        "stationMasterRows": stations[0],
        "gangnamMasterRows": stations[1],
        "model": {
            "version": model[0],
            "trainingStart": model[1],
            "trainingEnd": model[2],
            "trainingRows": model[3],
            "stationCount": model[4],
            "baselineRows": baseline_rows,
        } if model else None,
        "dateQuality": {
            "expectedDays": len(expected),
            "archiveDays": len(expected & available),
            "missingDays": sorted(expected - available),
            "emptyMembers": empty_members,
            "filenameDataDateMismatches": mismatches,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
