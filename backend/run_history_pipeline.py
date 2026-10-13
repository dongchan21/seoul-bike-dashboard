"""Run raw OA-21229 ZIP -> flows_5m -> station master -> baseline."""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.aggregate_flows import DEFAULT_DB, DEFAULT_RAW, connect, import_flow_zip
from backend.baseline import MODEL_VERSION, train_baseline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the historical flow pipeline end to end.")
    parser.add_argument("paths", nargs="*", type=Path, help="ZIP files; defaults to raw/*.zip")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--status", action="store_true", help="print table and latest run summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.status:
        with connect(args.db) as db:
            counts = {
                "flows5m": db.execute("SELECT count(*) FROM flows_5m").fetchone()[0],
                "stations": db.execute("SELECT count(*) FROM station_master").fetchone()[0],
                "stationsWithoutCoordinates": db.execute(
                    "SELECT count(*) FROM station_master WHERE latitude IS NULL OR longitude IS NULL"
                ).fetchone()[0],
                "imports": db.execute("SELECT count(*) FROM flow_imports").fetchone()[0],
            }
            model_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='baseline_models'"
            ).fetchone()
            counts["baselineRows"] = db.execute(
                "SELECT count(*) FROM baseline_5m"
            ).fetchone()[0] if model_table else 0
            latest_import = db.execute(
                "SELECT source_file, min_date, max_date, source_rows, dense_rows "
                "FROM flow_imports ORDER BY imported_at DESC LIMIT 1"
            ).fetchone()
            latest_model = db.execute(
                "SELECT model_version, training_start, training_end, training_rows, station_count "
                "FROM baseline_models ORDER BY trained_at DESC LIMIT 1"
            ).fetchone() if model_table else None
            print({"counts": counts, "latestImport": latest_import, "latestModel": latest_model})
        return 0
    paths = args.paths or sorted(DEFAULT_RAW.glob("*.zip"))
    if not paths:
        raise SystemExit(f"no ZIP files found under {DEFAULT_RAW}")
    with connect(args.db) as db:
        for path in paths:
            print(import_flow_zip(path, db, force=args.force))
        print(
            train_baseline(
                db,
                model_version=args.model_version,
                start_date=args.start_date,
                end_date=args.end_date,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
