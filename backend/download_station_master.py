"""Download and normalize the official Seoul Bike station master (OA-21235)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.aggregate_flows import DEFAULT_DB, connect


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "OA-21235"
DATASET_PAGE = f"https://data.seoul.go.kr/dataList/{DATASET_ID}/S/1/datasetView.do"
DATA_URL = "https://data.seoul.go.kr/dataList/dataView.do"
DEFAULT_OUTPUT = ROOT / "data" / "station_master" / "oa21235.json"


class StationMasterError(RuntimeError):
    """Raised when the official station master cannot be parsed safely."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def district_from_address(address: str) -> str | None:
    match = re.search(r"(?:서울특별시|서울시|서울)\s+([^\s]+구)\b", address.strip())
    return match.group(1) if match else None


def parse_data_view(payload: str) -> dict:
    """Convert Seoul's JavaScript-object response (unquoted keys) to JSON."""
    normalized = re.sub(r'([\{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', payload)
    normalized = re.sub(r",\s*([}\]])", r"\1", normalized)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise StationMasterError(f"invalid OA-21235 response: {exc}") from exc
    if parsed.get("result") != "ok" or not isinstance(parsed.get("list"), list):
        raise StationMasterError("OA-21235 response did not contain a successful list")
    return parsed


def _fetch_page(page_no: int, timeout: int) -> dict:
    query = urlencode(
        {
            "onepagerow": 1000,
            "srvType": "S",
            "infId": DATASET_ID,
            "serviceKind": 0,
            "pageNo": page_no,
            "ssUserId": "SAMPLE_VIEW",
            "strWhere": "",
            "strOrderby": "RNTLS_ID DESC",
        }
    )
    request = Request(f"{DATA_URL}?{query}", headers={"User-Agent": "seoul-bike-dashboard/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return parse_data_view(response.read().decode("utf-8-sig"))


def fetch_station_master(timeout: int = 60) -> list[dict[str, str | float | None]]:
    first = _fetch_page(1, timeout)
    page_count = int(first.get("page", {}).get("pageCount", 1))
    pages = [first] + [_fetch_page(page_no, timeout) for page_no in range(2, page_count + 1)]
    rows: dict[str, dict[str, str | float | None]] = {}
    for page in pages:
        for raw in page["list"]:
            station_id = str(raw.get("RNTLS_ID", "")).strip()
            if not station_id:
                continue
            address = str(raw.get("ADDR1", "")).strip()
            name = str(raw.get("ADDR2", "")).strip() or station_id
            try:
                latitude = float(raw["LAT"]) if raw.get("LAT") not in (None, "") else None
                longitude = float(raw["LOT"]) if raw.get("LOT") not in (None, "") else None
            except (TypeError, ValueError) as exc:
                raise StationMasterError(f"invalid coordinates for {station_id}") from exc
            if latitude == 0 or longitude == 0:
                latitude = longitude = None
            rows[station_id] = {
                "stationId": station_id,
                "stationName": name,
                "address": address,
                "district": district_from_address(address),
                "latitude": latitude,
                "longitude": longitude,
            }
    return sorted(rows.values(), key=lambda row: str(row["stationId"]))


def save_snapshot(rows: list[dict], path: Path = DEFAULT_OUTPUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "datasetId": DATASET_ID,
        "source": DATASET_PAGE,
        "fetchedAt": utcnow(),
        "rowCount": len(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_station_master(db: sqlite3.Connection, rows: list[dict]) -> int:
    timestamp = utcnow()
    db.executemany(
        """
        INSERT INTO station_master(
          station_id, station_name, capacity, latitude, longitude,
          source, updated_at, district, address
        ) VALUES(?,?,NULL,?,?,'oa-21235',?,?,?)
        ON CONFLICT(station_id) DO UPDATE SET
          station_name=CASE
            WHEN station_master.source='realtime-inventory' THEN station_master.station_name
            ELSE excluded.station_name
          END,
          latitude=COALESCE(excluded.latitude, station_master.latitude),
          longitude=COALESCE(excluded.longitude, station_master.longitude),
          district=excluded.district,
          address=excluded.address,
          updated_at=excluded.updated_at
        """,
        [
            (
                row["stationId"], row["stationName"], row["latitude"], row["longitude"],
                timestamp, row["district"], row["address"],
            )
            for row in rows
        ],
    )
    db.commit()
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download OA-21235 station master.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--district", help="print the number of stations in a district")
    parser.add_argument("--timeout", type=int, default=60)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = fetch_station_master(args.timeout)
    save_snapshot(rows, args.output)
    with connect(args.db) as db:
        upsert_station_master(db, rows)
        district_count = db.execute(
            "SELECT count(*) FROM station_master WHERE district=?", (args.district,)
        ).fetchone()[0] if args.district else None
    result = {"downloaded": len(rows), "snapshot": str(args.output), "db": str(args.db)}
    if args.district:
        result.update({"district": args.district, "districtStations": district_count})
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
