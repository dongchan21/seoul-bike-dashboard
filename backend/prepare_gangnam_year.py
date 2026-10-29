"""Build the reproducible Gangnam-gu one-year training dataset.

Window: 2025-10-09 through 2026-10-08 (inclusive).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.aggregate_flows import connect, import_flow_zip
from backend.baseline import MODEL_VERSION, train_baseline
from backend.download_history import download_file, fetch_catalog, select_entries
from backend.download_station_flow import CATALOG_URL, DATASET_ID, DATASET_PAGE, DEFAULT_OUTPUT
from backend.download_station_master import (
    DEFAULT_OUTPUT as MASTER_OUTPUT,
    fetch_station_master,
    save_snapshot,
    upsert_station_master,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "gangnam" / "gangnam.sqlite3"
DISTRICT = "강남구"
START_DATE = "2025-10-09"
END_DATE = "2026-10-08"
PERIODS = [
    "2025-10", "2025-11", "2025-12",
    "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
    "2026-07", "2026-08", "2026-09",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08",
]
FILENAMES = [
    f"tpss_bcycl_od_statnhm_{period.replace('-', '')}.zip" for period in PERIODS
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare one year of Gangnam Seoul Bike data.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument("--skip-train", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = fetch_station_master(args.timeout)
    save_snapshot(rows, MASTER_OUTPUT)
    with connect(args.db) as db:
        upsert_station_master(db, rows)
        district_count = db.execute(
            "SELECT count(*) FROM station_master WHERE district=?", (DISTRICT,)
        ).fetchone()[0]
    print({"district": DISTRICT, "stations": district_count, "db": str(args.db)})

    catalog = fetch_catalog(timeout=args.timeout, catalog_url=CATALOG_URL)
    selected = select_entries(catalog, filenames=FILENAMES)
    if not args.skip_download:
        manifest = args.raw_dir.parent / "manifest.json"
        for entry in selected:
            download_file(
                entry,
                output_dir=args.raw_dir,
                manifest_path=manifest,
                timeout=args.timeout,
                force=args.force,
                dataset_id=DATASET_ID,
                dataset_page=DATASET_PAGE,
                catalog_url=CATALOG_URL,
            )

    if not args.skip_import:
        with connect(args.db) as db:
            for entry in selected:
                print(
                    import_flow_zip(
                        args.raw_dir / entry.filename,
                        db,
                        force=args.force,
                        district=DISTRICT,
                        start_date=START_DATE,
                        end_date=END_DATE,
                    )
                )

    if not args.skip_train:
        with connect(args.db) as db:
            print(
                train_baseline(
                    db,
                    model_version=MODEL_VERSION,
                    start_date=START_DATE,
                    end_date=END_DATE,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
