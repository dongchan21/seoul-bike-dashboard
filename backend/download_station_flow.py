"""Download 5-minute station origin/destination counts from OA-21229.

Examples:
  python -m backend.download_station_flow --list
  python -m backend.download_station_flow --latest
  python -m backend.download_station_flow --period 2026-09
  python -m backend.download_station_flow --period 2026-10-07
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from backend.download_history import (
    HistoryDownloadError,
    download_file,
    fetch_catalog,
    print_catalog,
    select_entries,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "OA-21229"
DATASET_PAGE = f"https://data.seoul.go.kr/dataList/{DATASET_ID}/F/1/datasetView.do"
CATALOG_URL = f"https://data.seoul.go.kr/dataList/fileView.do?infId={DATASET_ID}&srvType=F"
DEFAULT_OUTPUT = ROOT / "data" / "station_flow" / "raw"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List and download Seoul Bike 5-minute station OD files (OA-21229)."
    )
    parser.add_argument("--list", action="store_true", help="list the official catalog")
    parser.add_argument(
        "--period",
        action="append",
        default=[],
        metavar="YYYY[-MM[-DD]]",
        help="download a month or daily file; repeatable",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="FILENAME",
        help="download an exact catalog filename; repeatable",
    )
    parser.add_argument("--latest", action="store_true", help="download the newest daily file")
    parser.add_argument("--dry-run", action="store_true", help="show selection only")
    parser.add_argument("--force", action="store_true", help="replace an existing verified file")
    parser.add_argument("--timeout", type=int, default=120, help="network timeout in seconds")
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT, help="raw download directory"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.list or args.period or args.file or args.latest):
        parser.error("choose --list, --period, --file, or --latest")

    try:
        catalog = fetch_catalog(timeout=args.timeout, catalog_url=CATALOG_URL)
        if args.list:
            print_catalog(catalog)
        selected = select_entries(catalog, args.period, args.file, args.latest)
        if not selected:
            return 0
        total = sum(entry.expected_bytes for entry in selected)
        print(f"Selected {len(selected)} file(s), about {total / 1024 / 1024:,.1f} MiB total")
        print_catalog(selected)
        if args.dry_run:
            return 0

        output_dir = args.output_dir.resolve()
        manifest_path = output_dir.parent / "manifest.json"
        for entry in selected:
            download_file(
                entry,
                output_dir=output_dir,
                manifest_path=manifest_path,
                timeout=args.timeout,
                force=args.force,
                dataset_id=DATASET_ID,
                dataset_page=DATASET_PAGE,
                catalog_url=CATALOG_URL,
            )
        return 0
    except (HistoryDownloadError, OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
