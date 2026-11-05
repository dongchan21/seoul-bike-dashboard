"""Check whether successful inventory snapshots are arriving every five minutes."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from backend.api import DEFAULT_DB_PATH


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "collection-health"
KST = timezone(timedelta(hours=9))
SLOT = timedelta(minutes=5)


def _floor_slot(moment: datetime) -> datetime:
    return moment.replace(minute=(moment.minute // 5) * 5, second=0, microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.astimezone(KST).isoformat()


def _missing_ranges(expected: list[datetime], actual: set[datetime]) -> list[dict]:
    ranges: list[dict] = []
    start: datetime | None = None
    previous: datetime | None = None
    for moment in expected:
        if moment not in actual:
            if start is None:
                start = moment
            previous = moment
        elif start is not None and previous is not None:
            ranges.append(
                {
                    "start": _iso(start),
                    "end": _iso(previous),
                    "missingSlots": int((previous - start) / SLOT) + 1,
                }
            )
            start = previous = None
    if start is not None and previous is not None:
        ranges.append(
            {
                "start": _iso(start),
                "end": _iso(previous),
                "missingSlots": int((previous - start) / SLOT) + 1,
            }
        )
    return ranges


def analyze_slots(
    slot_values: list[str],
    *,
    now: datetime | None = None,
    days: int = 7,
    delayed_after_minutes: int = 10,
    minimum_coverage: float = 0.95,
) -> dict:
    if days < 1:
        raise ValueError("days must be at least 1")
    current = _floor_slot((now or datetime.now(timezone.utc)).astimezone(KST))
    range_start = datetime.combine(
        current.date() - timedelta(days=days - 1), time.min, tzinfo=KST
    )
    actual_all = sorted({datetime.fromisoformat(value).astimezone(KST) for value in slot_values})
    actual = {value for value in actual_all if range_start <= value <= current}
    expected: list[datetime] = []
    cursor = range_start
    while cursor <= current:
        expected.append(cursor)
        cursor += SLOT
    missing = _missing_ranges(expected, actual)
    expected_count = len(expected)
    success_count = len(actual)
    coverage = success_count / expected_count if expected_count else 0.0
    last_success = actual_all[-1] if actual_all else None
    age_minutes = (
        max(0.0, (current - last_success).total_seconds() / 60)
        if last_success is not None
        else None
    )
    delayed = age_minutes is None or age_minutes > delayed_after_minutes
    incomplete = coverage < minimum_coverage
    status = "delayed" if delayed else "incomplete" if incomplete else "normal"

    daily = []
    for offset in range(days):
        day = range_start.date() + timedelta(days=offset)
        day_start = datetime.combine(day, time.min, tzinfo=KST)
        day_end = min(current, day_start + timedelta(days=1) - SLOT)
        if day_start > current:
            continue
        day_expected = int((day_end - day_start) / SLOT) + 1
        day_success = sum(day_start <= value <= day_end for value in actual)
        daily.append(
            {
                "date": day.isoformat(),
                "expectedSlots": day_expected,
                "successfulSlots": day_success,
                "missingSlots": day_expected - day_success,
                "coverage": round(day_success / day_expected, 6) if day_expected else 0.0,
            }
        )

    return {
        "status": status,
        "checkedAt": _iso(current),
        "range": {"start": _iso(range_start), "end": _iso(current), "days": days},
        "lastSuccessAt": _iso(last_success) if last_success else None,
        "lastSuccessAgeMinutes": round(age_minutes, 2) if age_minutes is not None else None,
        "expectedSlots": expected_count,
        "successfulSlots": success_count,
        "missingSlots": expected_count - success_count,
        "coverage": round(coverage, 6),
        "thresholds": {
            "delayedAfterMinutes": delayed_after_minutes,
            "minimumCoverage": minimum_coverage,
        },
        "longestMissingSlots": max((item["missingSlots"] for item in missing), default=0),
        "missingRanges": missing,
        "daily": daily,
    }


def inspect_database(
    path: Path,
    *,
    now: datetime | None = None,
    days: int = 7,
    delayed_after_minutes: int = 10,
    minimum_coverage: float = 0.95,
) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
        values = [row[0] for row in connection.execute("SELECT slot FROM slots ORDER BY slot")]
    finally:
        connection.close()
    return analyze_slots(
        values,
        now=now,
        days=days,
        delayed_after_minutes=delayed_after_minutes,
        minimum_coverage=minimum_coverage,
    )


def write_report(result: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "latest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "daily.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(result["daily"][0]))
        writer.writeheader()
        writer.writerows(result["daily"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--delayed-after-minutes", type=int, default=10)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fail-on-unhealthy", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_database(
        args.db,
        days=args.days,
        delayed_after_minutes=args.delayed_after_minutes,
        minimum_coverage=args.minimum_coverage,
    )
    write_report(result, args.output_dir)
    print(json.dumps({key: result[key] for key in (
        "status", "checkedAt", "lastSuccessAt", "lastSuccessAgeMinutes",
        "expectedSlots", "successfulSlots", "missingSlots", "coverage",
        "longestMissingSlots",
    )}, ensure_ascii=False, indent=2))
    return 2 if args.fail_on_unhealthy and result["status"] != "normal" else 0


if __name__ == "__main__":
    raise SystemExit(main())
