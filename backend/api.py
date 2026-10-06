"""Read-only API for the collected Seoul bike inventory."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "inventory" / "inventory.sqlite3"


def database_path() -> Path:
    return Path(os.getenv("INVENTORY_DB_PATH", DEFAULT_DB_PATH)).resolve()


@contextmanager
def read_connection(path: Path | None = None):
    selected = path or database_path()
    if not selected.is_file():
        raise FileNotFoundError(selected)
    connection = sqlite3.connect(
        f"{selected.as_uri()}?mode=ro",
        uri=True,
        timeout=5,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    try:
        yield connection
    finally:
        connection.close()


def inventory_status(path: Path | None = None) -> dict:
    with read_connection(path) as db:
        latest = db.execute(
            """
            SELECT r.id, r.slot, r.started_at, r.finished_at, r.row_count
            FROM runs r JOIN slots s ON s.run_id = r.id
            ORDER BY s.slot DESC LIMIT 1
            """
        ).fetchone()
        recent = db.execute(
            "SELECT status, error, started_at FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if latest is None:
        raise LookupError("no_successful_collection")
    slot = datetime.fromisoformat(latest["slot"])
    age_seconds = max(0, int((datetime.now(timezone.utc) - slot).total_seconds()))
    return {
        "runId": latest["id"],
        "slot": latest["slot"],
        "startedAt": latest["started_at"],
        "finishedAt": latest["finished_at"],
        "stationCount": latest["row_count"],
        "ageSeconds": age_seconds,
        "dataQuality": "delayed" if age_seconds > 600 else "normal",
        "lastRunStatus": recent["status"] if recent else None,
        "lastRunError": recent["error"] if recent else None,
    }


def latest_stations(path: Path | None = None) -> list[dict]:
    with read_connection(path) as db:
        rows = db.execute(
            """
            SELECT station_id, name, rack_count, current_bikes, shared,
                   latitude, longitude, fetched_at, slot
            FROM latest_inventory
            ORDER BY station_id
            """
        ).fetchall()
    return [
        {
            "stationId": row["station_id"],
            "stationName": row["name"],
            "capacity": row["rack_count"],
            "currentBikes": row["current_bikes"],
            "occupancyRate": row["shared"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "fetchedAt": row["fetched_at"],
            "slot": row["slot"],
        }
        for row in rows
    ]


def station_history(station_id: str, limit: int, path: Path | None = None) -> list[dict]:
    with read_connection(path) as db:
        rows = db.execute(
            """
            SELECT o.current_bikes, o.shared, o.fetched_at, r.slot
            FROM observations o JOIN runs r ON r.id = o.run_id
            WHERE o.station_id = ? AND r.status = 'success'
            ORDER BY r.slot DESC LIMIT ?
            """,
            (station_id, limit),
        ).fetchall()
    return [
        {
            "currentBikes": row["current_bikes"],
            "occupancyRate": row["shared"],
            "fetchedAt": row["fetched_at"],
            "slot": row["slot"],
        }
        for row in reversed(rows)
    ]


app = FastAPI(title="따릉이 실시간 재고 API", version="0.1.0")
origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def unavailable(exc: Exception) -> HTTPException:
    detail = "수집 데이터베이스가 없습니다." if isinstance(exc, FileNotFoundError) else "정상 수집 결과가 없습니다."
    return HTTPException(status_code=503, detail=detail)


@app.get("/health")
def health():
    try:
        return {"status": "ok", "inventory": inventory_status()}
    except (FileNotFoundError, sqlite3.Error, LookupError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/status")
def status():
    try:
        return inventory_status()
    except (FileNotFoundError, sqlite3.Error, LookupError) as exc:
        raise unavailable(exc) from exc


@app.get("/api/stations")
def stations():
    try:
        rows = latest_stations()
    except (FileNotFoundError, sqlite3.Error) as exc:
        raise unavailable(exc) from exc
    if not rows:
        raise HTTPException(status_code=503, detail="최신 대여소 데이터가 비어 있습니다.")
    return rows


@app.get("/api/stations/{station_id}/history")
def history(station_id: str, limit: int = Query(default=13, ge=1, le=288)):
    try:
        rows = station_history(station_id, limit)
    except (FileNotFoundError, sqlite3.Error) as exc:
        raise unavailable(exc) from exc
    if not rows:
        raise HTTPException(status_code=404, detail="대여소 이력을 찾을 수 없습니다.")
    return rows
