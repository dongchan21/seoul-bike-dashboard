"""Standard-library-only collector. Run: python -m backend.collect --once"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://openapi.seoul.go.kr:8088"


class CollectionError(Exception):
    pass


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def fetch_page(key, start, end, archive, timeout=20):
    # Never log request URLs: Seoul puts the API key in the URL path.
    from urllib.parse import quote
    url = f"{BASE_URL}/{quote(key, safe='')}/json/bikeList/{start}/{end}/"
    for attempt in range(1, 4):
        try:
            with urlopen(Request(url, headers={"User-Agent": "bike-inventory/1.0"}), timeout=timeout) as response:
                payload = response.read(10_000_001)
            if len(payload) > 10_000_000:
                raise CollectionError("response_too_large")
            # Keep successful HTTP bodies, including invalid JSON / API errors.
            with gzip.open(archive / f"{start}-{end}-attempt{attempt}.json.gz", "wb") as out:
                out.write(payload.replace(key.encode(), b"[REDACTED]"))
            parsed = json.loads(payload)
            if not isinstance(parsed, dict):
                raise CollectionError("invalid_response_structure")
            return parsed
        except HTTPError as exc:
            exc.close()
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise CollectionError(f"http_{exc.code}") from None
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass
        if attempt < 3:
            time.sleep(2 ** attempt + random.random())
    raise CollectionError("request_failed_after_3_attempts")


def page_rows(payload):
    node = payload.get("rentBikeStatus", payload.get("bikeList", payload))
    if not isinstance(node, dict):
        raise CollectionError("invalid_response_structure")
    result = node.get("RESULT", payload.get("RESULT", {}))
    code = result.get("CODE") if isinstance(result, dict) else None
    if code == "INFO-200":
        return []
    if code != "INFO-000":
        # Whitelist the error code only; server messages might contain the key.
        safe = code if isinstance(code, str) and code.replace("-", "").isalnum() else "unknown"
        raise CollectionError(f"api_{safe}")
    rows = node.get("row")
    if not isinstance(rows, list):
        raise CollectionError("missing_rows")
    return rows


def normalize(row):
    try:
        sid = row["stationId"]
        name = row["stationName"]
        if not isinstance(sid, str) or not sid.strip() or not isinstance(name, str):
            raise ValueError()
        rack, bikes = float(row["rackTotCnt"]), float(row["parkingBikeTotCnt"])
        lat, lng = float(row["stationLatitude"]), float(row["stationLongitude"])
        rate = float(row["shared"])
        if not all(math.isfinite(v) for v in (rack, bikes, lat, lng, rate)):
            raise ValueError()
        if rack < 0 or bikes < 0 or not rack.is_integer() or not bikes.is_integer():
            raise ValueError()
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError()
        return (sid.strip(), name, int(rack), int(bikes), rate, lat, lng)
    except (KeyError, ValueError, TypeError):
        raise CollectionError("invalid_station_row") from None


def connect(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(data_dir / "inventory.sqlite3", timeout=10)
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, slot TEXT, started_at TEXT, finished_at TEXT,
          status TEXT, row_count INTEGER, error TEXT);
        CREATE TABLE IF NOT EXISTS observations (
          run_id TEXT, station_id TEXT, name TEXT, rack_count INTEGER,
          current_bikes INTEGER, shared REAL, latitude REAL, longitude REAL,
          fetched_at TEXT, source_observed_at TEXT,
          PRIMARY KEY(run_id, station_id));
        CREATE TABLE IF NOT EXISTS slots (
          slot TEXT PRIMARY KEY, run_id TEXT NOT NULL);
        CREATE VIEW IF NOT EXISTS latest_inventory AS
          SELECT o.*, r.slot FROM observations o JOIN runs r ON o.run_id=r.id
          WHERE o.run_id=(SELECT run_id FROM slots ORDER BY slot DESC LIMIT 1);
    """)
    return db


@contextmanager
def collector_lock(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".collector.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise CollectionError("collector_already_running") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise CollectionError("collector_already_running") from None
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def collect(db, data_dir, key, fetch=fetch_page, timestamp=None, page_size=1000):
    epoch = time.time() if timestamp is None else timestamp
    slot = datetime.fromtimestamp(int(epoch // 300) * 300, timezone.utc).isoformat()
    if db.execute("SELECT 1 FROM slots WHERE slot=?", (slot,)).fetchone():
        return {"status": "skipped", "slot": slot}
    rid = uuid4().hex
    archive = data_dir / "raw" / slot[:10] / rid
    archive.mkdir(parents=True)
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (rid, slot, utcnow(), None, "running", 0, None))
    db.commit()
    seen = set()
    error = None
    try:
        # Do not trust list_total_count as a global total: its meaning can vary.
        for start in range(1, 100_001, page_size):
            rows = page_rows(fetch(key, start, start + page_size - 1, archive))
            if len(rows) > page_size:
                raise CollectionError("oversized_page")
            fetched = utcnow()
            normalized = []
            for row in rows:
                values = normalize(row)
                if values[0] in seen:
                    raise CollectionError("duplicate_station_across_pages")
                seen.add(values[0])
                normalized.append((rid, *values, fetched, None))
            db.executemany("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)", normalized)
            db.commit()
            if len(rows) < page_size:
                break
        else:
            raise CollectionError("pagination_limit_exceeded")
        if not seen:
            raise CollectionError("empty_inventory")
        status = "success"
    except KeyboardInterrupt:
        error, status = "interrupted", "failed"
    except Exception as exc:
        error = str(exc) if isinstance(exc, CollectionError) else type(exc).__name__
        status = "partial" if db.execute("SELECT 1 FROM observations WHERE run_id=?", (rid,)).fetchone() else "failed"
    count = db.execute("SELECT count(*) FROM observations WHERE run_id=?", (rid,)).fetchone()[0]
    with db:
        db.execute("UPDATE runs SET finished_at=?,status=?,row_count=?,error=? WHERE id=?",
                   (utcnow(), status, count, error, rid))
        if status == "success":
            db.execute("INSERT INTO slots VALUES(?,?)", (slot, rid))
    if error == "interrupted":
        raise KeyboardInterrupt
    return {"run_id": rid, "slot": slot, "status": status, "rows": count, "error": error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Collect once and exit")
    parser.add_argument("--status", action="store_true", help="Read recent run statuses")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "inventory")
    args = parser.parse_args()
    load_env()
    if args.status:
        path = args.data_dir / "inventory.sqlite3"
        if not path.exists():
            print("No collection database yet.")
            return 0
        with sqlite3.connect(path) as db:
            for row in db.execute("SELECT slot,status,row_count,error FROM runs ORDER BY started_at DESC LIMIT 10"):
                print(json.dumps(row, ensure_ascii=False))
        return 0
    key = os.getenv("SEOUL_API_KEY", "").strip()
    if not key or key == "YOUR_API_KEY" or key == "sample":
        print("Set SEOUL_API_KEY in the project .env file (a real key is required).")
        return 2
    try:
        with collector_lock(args.data_dir):
            db = connect(args.data_dir)
            try:
                with db:
                    db.execute("UPDATE runs SET status='failed',error='previous_process_stopped',finished_at=? WHERE status='running'", (utcnow(),))
                while True:
                    result = collect(db, args.data_dir, key)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                    if args.once:
                        return 0 if result["status"] in ("success", "skipped") else 1
                    time.sleep(300 - time.time() % 300)
            finally:
                db.close()
    except KeyboardInterrupt:
        print("Collector stopped.")
        return 0
    except (CollectionError, OSError, sqlite3.Error) as exc:
        print(str(exc) if isinstance(exc, CollectionError) else type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
