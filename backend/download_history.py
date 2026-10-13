"""Download official Seoul Bike trip history files.

The catalog is OA-15182 on the Seoul Data Hub. Files are intentionally kept
as immutable raw inputs; parsing and 5-minute aggregation belong in a separate
step.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Iterable
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DATASET_ID = "OA-15182"
DATASET_PAGE = f"https://data.seoul.go.kr/dataList/{DATASET_ID}/F/1/datasetView.do"
CATALOG_URL = f"https://data.seoul.go.kr/dataList/fileView.do?infId={DATASET_ID}&srvType=F"
DOWNLOAD_URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?useCache=false"
DEFAULT_OUTPUT = ROOT / "data" / "history" / "raw"
USER_AGENT = "seoul-bike-history/1.0"
CHUNK_SIZE = 4 * 1024 * 1024


class HistoryDownloadError(RuntimeError):
    """Raised when the catalog or downloaded file is not trustworthy."""


@dataclass(frozen=True)
class HistoryFile:
    seq: str
    filename: str
    size_kib: float
    published_at: str
    updated_at: str

    @property
    def expected_bytes(self) -> int:
        return round(self.size_kib * 1024)

    @property
    def period(self) -> str | None:
        daily = re.search(r"_(20\d{2})(\d{2})(\d{2})\.zip$", self.filename, re.IGNORECASE)
        if daily:
            return f"{daily.group(1)}-{daily.group(2)}-{daily.group(3)}"
        monthly_zip = re.search(r"_(20\d{2})(\d{2})\.zip$", self.filename, re.IGNORECASE)
        if monthly_zip:
            return f"{monthly_zip.group(1)}-{monthly_zip.group(2)}"
        annual = re.search(r"_(20\d{2})\.zip$", self.filename, re.IGNORECASE)
        if annual:
            return annual.group(1)
        monthly = re.search(r"_(\d{2})(\d{2})\.csv$", self.filename, re.IGNORECASE)
        if monthly:
            return f"20{monthly.group(1)}-{monthly.group(2)}"
        return None


def _cell_text(fragment: str) -> str:
    return unescape(re.sub(r"(?is)<[^>]+>", "", fragment)).strip()


def parse_catalog(html_text: str) -> list[HistoryFile]:
    """Parse file rows returned by the official fileView endpoint."""
    entries: list[HistoryFile] = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html_text):
        seq_match = re.search(r"downloadFile\('([^']+)'\)", row)
        if not seq_match:
            continue
        cells = [
            _cell_text(cell)
            for cell in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)
        ]
        if len(cells) < 5:
            continue
        try:
            size_kib = float(cells[2].replace(",", ""))
        except ValueError as exc:
            raise HistoryDownloadError(f"invalid catalog size: {cells[2]!r}") from exc
        filename = cells[1]
        if Path(filename).name != filename:
            raise HistoryDownloadError(f"unsafe catalog filename: {filename!r}")
        entries.append(
            HistoryFile(
                seq=seq_match.group(1),
                filename=filename,
                size_kib=size_kib,
                published_at=cells[3],
                updated_at=cells[4],
            )
        )
    if not entries:
        raise HistoryDownloadError("no downloadable files found in the official catalog")
    return entries


def fetch_catalog(timeout: int = 30, catalog_url: str = CATALOG_URL) -> list[HistoryFile]:
    request = Request(
        catalog_url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(10_000_001)
    if len(payload) > 10_000_000:
        raise HistoryDownloadError("catalog response exceeded 10 MB")
    return parse_catalog(payload.decode("utf-8-sig"))


def _period_sort_key(entry: HistoryFile) -> tuple[int, int, int]:
    if entry.period and len(entry.period) == 10:
        return int(entry.period[:4]), int(entry.period[5:7]), int(entry.period[8:])
    if entry.period and len(entry.period) == 7:
        return int(entry.period[:4]), int(entry.period[5:]), 31
    if entry.period:
        return int(entry.period), 12, 31
    return 0, 0, 0


def select_entries(
    catalog: Iterable[HistoryFile],
    periods: Iterable[str] = (),
    filenames: Iterable[str] = (),
    latest: bool = False,
) -> list[HistoryFile]:
    entries = list(catalog)
    selected: list[HistoryFile] = []
    period_values = list(periods)
    filename_values = list(filenames)

    for period in period_values:
        if not re.fullmatch(
            r"20\d{2}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?",
            period,
        ):
            raise HistoryDownloadError(
                f"invalid period {period!r}; use YYYY, YYYY-MM, or YYYY-MM-DD"
            )
        matches = [
            entry
            for entry in entries
            if entry.period == period or entry.period.startswith(period + "-")
        ]
        if not matches:
            raise HistoryDownloadError(f"period not found in catalog: {period}")
        selected.extend(matches)

    for filename in filename_values:
        matches = [entry for entry in entries if entry.filename == filename]
        if not matches:
            raise HistoryDownloadError(f"filename not found in catalog: {filename}")
        selected.extend(matches)

    if latest:
        selected.append(max(entries, key=_period_sort_key))

    unique: dict[str, HistoryFile] = {}
    for entry in selected:
        unique[entry.filename] = entry
    return sorted(unique.values(), key=_period_sort_key)


def parse_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", value, re.IGNORECASE)
    if encoded:
        filename = unquote(encoded.group(1).strip().strip('"'))
        return Path(_repair_header_encoding(filename)).name
    basic = re.search(r"filename\s*=\s*(?:\"([^\"]+)\"|([^;]+))", value, re.IGNORECASE)
    if not basic:
        return None
    filename = unquote((basic.group(1) or basic.group(2)).strip())
    return Path(_repair_header_encoding(filename)).name


def _repair_header_encoding(value: str) -> str:
    """Repair UTF-8 bytes exposed as ISO-8859-1 by HTTP header parsing."""
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _size_matches(actual: int, expected: int) -> bool:
    tolerance = max(4096, round(expected * 0.0001))
    return abs(actual - expected) <= tolerance


def validate_file(path: Path, entry: HistoryFile) -> None:
    if not path.is_file():
        raise HistoryDownloadError(f"downloaded file is missing: {path}")
    actual_size = path.stat().st_size
    if not _size_matches(actual_size, entry.expected_bytes):
        raise HistoryDownloadError(
            f"size mismatch for {entry.filename}: {actual_size:,} bytes, "
            f"catalog expects about {entry.expected_bytes:,} bytes"
        )

    with path.open("rb") as file:
        sample = file.read(4096)
    lowered = sample.lstrip().lower()
    if lowered.startswith((b"<html", b"<!doctype html")):
        raise HistoryDownloadError(f"HTML error page was saved instead of {entry.filename}")
    if path.suffix.lower() == ".zip" and not zipfile.is_zipfile(path):
        raise HistoryDownloadError(f"invalid ZIP file: {entry.filename}")
    if path.suffix.lower() == ".csv":
        csv_like = False
        for encoding in ("utf-8-sig", "cp949"):
            try:
                text = sample.decode(encoding)
            except UnicodeDecodeError:
                continue
            if "," in text and ("\n" in text or "\r" in text):
                csv_like = True
                break
        if not csv_like:
            raise HistoryDownloadError(f"download does not look like CSV: {entry.filename}")


def _load_manifest(path: Path, dataset_id: str = DATASET_ID) -> dict:
    if not path.exists():
        return {"dataset_id": dataset_id, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryDownloadError(f"invalid manifest: {path}") from exc
    if data.get("dataset_id") != dataset_id or not isinstance(data.get("files"), dict):
        raise HistoryDownloadError(f"unexpected manifest structure: {path}")
    return data


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def download_file(
    entry: HistoryFile,
    output_dir: Path,
    manifest_path: Path,
    timeout: int = 120,
    force: bool = False,
    dataset_id: str = DATASET_ID,
    dataset_page: str = DATASET_PAGE,
    catalog_url: str = CATALOG_URL,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / entry.filename
    partial = output_dir / f"{entry.filename}.part"

    if destination.exists() and not force:
        validate_file(destination, entry)
        print(f"SKIP  {entry.filename} (already verified)")
        return destination

    form = urlencode(
        {"infId": dataset_id, "seqNo": "", "seq": entry.seq, "infSeq": "1"}
    ).encode("ascii")
    request = Request(
        DOWNLOAD_URL,
        data=form,
        method="POST",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://data.seoul.go.kr",
            "Referer": dataset_page,
        },
    )

    digest = sha256()
    downloaded = 0
    last_report = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type().lower()
            remote_name = parse_disposition_filename(
                response.headers.get("Content-Disposition")
            )
            if content_type in {"text/html", "application/xhtml+xml"}:
                error_sample = response.read(1000).decode("utf-8", "replace")
                raise HistoryDownloadError(
                    "official server returned an HTML error page: "
                    + re.sub(r"\s+", " ", _cell_text(error_sample))[:300]
                )
            if remote_name != entry.filename:
                raise HistoryDownloadError(
                    f"server filename mismatch: expected {entry.filename!r}, got {remote_name!r}"
                )
            content_length = response.headers.get("Content-Length")
            if content_length and not _size_matches(int(content_length), entry.expected_bytes):
                raise HistoryDownloadError(
                    f"server size mismatch for {entry.filename}: {int(content_length):,} bytes"
                )

            print(f"GET   {entry.filename} ({entry.expected_bytes / 1024 / 1024:,.1f} MiB)")
            with partial.open("wb") as file:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    file.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 5:
                        percentage = downloaded / entry.expected_bytes * 100
                        print(
                            f"      {downloaded / 1024 / 1024:,.1f} MiB "
                            f"({percentage:5.1f}%)",
                            flush=True,
                        )
                        last_report = now
                file.flush()
                os.fsync(file.fileno())
        validate_file(partial, entry)
        os.replace(partial, destination)
    except Exception:
        if partial.exists():
            print(f"KEEP  incomplete file for inspection: {partial}", file=sys.stderr)
        raise

    manifest = _load_manifest(manifest_path, dataset_id=dataset_id)
    manifest["catalog_url"] = catalog_url
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["files"][entry.filename] = {
        **asdict(entry),
        "bytes": destination.stat().st_size,
        "sha256": digest.hexdigest(),
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "path": destination.relative_to(ROOT).as_posix()
        if destination.is_relative_to(ROOT)
        else str(destination),
    }
    _write_manifest(manifest_path, manifest)
    print(f"OK    {entry.filename} sha256={digest.hexdigest()}")
    return destination


def print_catalog(entries: Iterable[HistoryFile]) -> None:
    print(f"{'PERIOD':<8} {'SIZE(MiB)':>11}  {'UPDATED':<10}  FILENAME")
    for entry in entries:
        print(
            f"{(entry.period or '-'):<8} "
            f"{entry.expected_bytes / 1024 / 1024:>11,.1f}  "
            f"{entry.updated_at:<10}  {entry.filename}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List and download official Seoul Bike trip history files (OA-15182)."
    )
    parser.add_argument("--list", action="store_true", help="list the official catalog")
    parser.add_argument(
        "--period",
        action="append",
        default=[],
        metavar="YYYY[-MM]",
        help="download a year archive or one monthly file; repeatable",
    )
    parser.add_argument(
        "--file",
        action="append",
        default=[],
        metavar="FILENAME",
        help="download an exact catalog filename; repeatable",
    )
    parser.add_argument("--latest", action="store_true", help="download the newest period")
    parser.add_argument("--dry-run", action="store_true", help="show selection without downloading")
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
        catalog = fetch_catalog(timeout=args.timeout)
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
            )
        return 0
    except (HistoryDownloadError, OSError, ValueError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
