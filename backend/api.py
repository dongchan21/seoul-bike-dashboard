"""Read-only API for the collected Seoul bike inventory."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from math import ceil
import os
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "inventory" / "inventory.sqlite3"
DEFAULT_PREDICTION_DB_PATH = ROOT / "data" / "gangnam" / "gangnam.sqlite3"
MODEL_VERSION = "seasonal-mean-v1"
KST = timezone(timedelta(hours=9))


def database_path() -> Path:
    return Path(os.getenv("INVENTORY_DB_PATH", DEFAULT_DB_PATH)).resolve()


def prediction_database_path() -> Path:
    return Path(os.getenv("PREDICTION_DB_PATH", DEFAULT_PREDICTION_DB_PATH)).resolve()


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


def prediction_model_status(path: Path | None = None) -> dict | None:
    selected = path or prediction_database_path()
    if not selected.is_file():
        return None
    with read_connection(selected) as db:
        row = db.execute(
            """SELECT model_version, trained_at, training_start, training_end,
                      training_rows, station_count
               FROM baseline_models WHERE model_version=?""",
            (MODEL_VERSION,),
        ).fetchone()
    if row is None:
        return None
    return {
        "modelVersion": row["model_version"],
        "trainedAt": row["trained_at"],
        "trainingStart": row["training_start"],
        "trainingEnd": row["training_end"],
        "trainingRows": row["training_rows"],
        "stationCount": row["station_count"],
        "horizonMinutes": 30,
        "method": "station-weekday-5minute-mean",
    }


def baseline_predictions(as_of: datetime, path: Path | None = None) -> dict[str, dict]:
    selected = path or prediction_database_path()
    if not selected.is_file():
        return {}
    moment = as_of.astimezone(KST) if as_of.tzinfo else as_of.replace(tzinfo=KST)
    slot = moment.replace(minute=(moment.minute // 5) * 5, second=0, microsecond=0)
    requested = [slot + timedelta(minutes=offset) for offset in range(0, 30, 5)]
    values = ",".join("(?,?)" for _ in requested)
    params: list[int | str] = []
    for item in requested:
        params.extend([item.weekday(), item.hour * 60 + item.minute])
    params.append(MODEL_VERSION)
    with read_connection(selected) as db:
        rows = db.execute(
            f"""WITH requested(weekday, minute_of_day) AS (VALUES {values})
                SELECT b.station_id, m.district, m.address,
                       sum(b.expected_rentals) AS rentals,
                       sum(b.expected_returns) AS returns,
                       count(*) AS slot_count
                FROM baseline_5m b
                JOIN requested r ON r.weekday=b.weekday
                                AND r.minute_of_day=b.minute_of_day
                LEFT JOIN station_master m ON m.station_id=b.station_id
                WHERE b.model_version=?
                GROUP BY b.station_id, m.district, m.address
                HAVING count(*)=6""",
            params,
        ).fetchall()
    return {
        row["station_id"]: {
            "district": row["district"],
            "address": row["address"],
            "expectedRentals30m": round(float(row["rentals"]), 2),
            "expectedReturns30m": round(float(row["returns"]), 2),
            "predictionAsOf": slot.isoformat(),
            "modelVersion": MODEL_VERSION,
        }
        for row in rows
    }


def inventory_status(
    path: Path | None = None, prediction_path: Path | None = None
) -> dict:
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
    result = {
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
    selected_prediction = prediction_path if prediction_path is not None else (
        prediction_database_path() if path is None else None
    )
    result["predictionModel"] = (
        prediction_model_status(selected_prediction) if selected_prediction else None
    )
    return result


def latest_stations(
    path: Path | None = None,
    prediction_path: Path | None = None,
    as_of: datetime | None = None,
) -> list[dict]:
    with read_connection(path) as db:
        rows = db.execute(
            """
            SELECT station_id, name, rack_count, current_bikes, shared,
                   latitude, longitude, fetched_at, slot
            FROM latest_inventory
            ORDER BY station_id
            """
        ).fetchall()
    selected_prediction = prediction_path if prediction_path is not None else (
        prediction_database_path() if path is None else None
    )
    prediction_time = as_of or datetime.fromisoformat(rows[0]["slot"]) if rows else None
    predictions = (
        baseline_predictions(prediction_time, selected_prediction)
        if prediction_time is not None and selected_prediction is not None
        else {}
    )
    result = []
    for row in rows:
        station = {
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
        prediction = predictions.get(row["station_id"])
        if prediction is None:
            station.update(
                {
                    "predictionAvailable": False,
                    "district": None,
                    "address": None,
                    "expectedRentals30m": None,
                    "expectedReturns30m": None,
                    "expectedBikes30m": None,
                    "forecastStatus": None,
                    "recommendedAction": None,
                    "recommendedQuantity": 0,
                    "priority": None,
                    "predictionAsOf": None,
                    "modelVersion": None,
                }
            )
        else:
            expected = round(
                row["current_bikes"]
                + prediction["expectedReturns30m"]
                - prediction["expectedRentals30m"],
                2,
            )
            capacity = max(0, row["rack_count"])
            low, high, target = capacity * 0.2, capacity * 0.8, capacity * 0.5
            if expected <= low:
                forecast_status, action = "shortage", "replenish"
                quantity = max(0, ceil(target - expected))
            elif capacity > 0 and expected >= high:
                forecast_status, action = "surplus", "collect"
                quantity = max(0, ceil(expected - target))
            else:
                forecast_status, action, quantity = "normal", "none", 0
            station.update(
                {
                    "predictionAvailable": True,
                    **prediction,
                    "expectedBikes30m": expected,
                    "forecastStatus": forecast_status,
                    "recommendedAction": action,
                    "recommendedQuantity": quantity,
                    "priority": None,
                }
            )
        result.append(station)

    predicted = [station for station in result if station["predictionAvailable"]]
    predicted.sort(
        key=lambda station: (
            0 if station["forecastStatus"] == "shortage" else 1 if station["forecastStatus"] == "surplus" else 2,
            -station["recommendedQuantity"],
            station["expectedBikes30m"],
        )
    )
    for priority, station in enumerate(predicted, start=1):
        station["priority"] = priority
    return result


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
