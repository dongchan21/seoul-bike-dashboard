"""Historical weekday/time mean baseline for 5-minute station flows."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from backend.aggregate_flows import DEFAULT_DB, connect, utcnow


MODEL_VERSION = "seasonal-mean-v1"
KST = timezone(timedelta(hours=9))


def ensure_baseline_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS baseline_models (
          model_version TEXT PRIMARY KEY,
          trained_at TEXT NOT NULL,
          training_start TEXT NOT NULL,
          training_end TEXT NOT NULL,
          training_rows INTEGER NOT NULL,
          station_count INTEGER NOT NULL,
          notes TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS baseline_5m (
          model_version TEXT NOT NULL,
          station_id TEXT NOT NULL,
          weekday INTEGER NOT NULL CHECK(weekday BETWEEN 0 AND 6),
          minute_of_day INTEGER NOT NULL CHECK(minute_of_day BETWEEN 0 AND 1435),
          sample_count INTEGER NOT NULL,
          expected_rentals REAL NOT NULL,
          expected_returns REAL NOT NULL,
          PRIMARY KEY(model_version, station_id, weekday, minute_of_day)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_baseline_lookup
          ON baseline_5m(station_id, weekday, minute_of_day);
        """
    )


def train_baseline(
    db: sqlite3.Connection,
    *,
    model_version: str = MODEL_VERSION,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, int | str]:
    ensure_baseline_schema(db)
    conditions: list[str] = []
    params: list[str] = []
    if start_date:
        conditions.append("service_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("service_date <= ?")
        params.append(end_date)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    stats = db.execute(
        f"""
        SELECT count(*), count(DISTINCT station_id), min(service_date), max(service_date)
        FROM flows_5m{where}
        """,
        params,
    ).fetchone()
    training_rows, station_count, training_start, training_end = stats
    if not training_rows:
        raise ValueError("flows_5m has no rows for the requested training period")

    trained_at = utcnow()
    db.execute("DELETE FROM baseline_5m WHERE model_version=?", (model_version,))
    db.execute("DELETE FROM baseline_models WHERE model_version=?", (model_version,))
    db.execute(
        f"""
        INSERT INTO baseline_5m(
          model_version, station_id, weekday, minute_of_day,
          sample_count, expected_rentals, expected_returns
        )
        SELECT ?, station_id,
               (CAST(strftime('%w', service_date) AS INTEGER) + 6) % 7,
               minute_of_day, count(*), avg(rentals), avg(returns)
        FROM flows_5m{where}
        GROUP BY station_id,
                 (CAST(strftime('%w', service_date) AS INTEGER) + 6) % 7,
                 minute_of_day
        """,
        [model_version, *params],
    )
    baseline_rows = db.execute(
        "SELECT count(*) FROM baseline_5m WHERE model_version=?", (model_version,)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO baseline_models VALUES(?,?,?,?,?,?,?)",
        (
            model_version,
            trained_at,
            training_start,
            training_end,
            training_rows,
            station_count,
            "station + weekday + 5-minute historical mean; missing observations are dense zero rows",
        ),
    )
    db.commit()
    return {
        "modelVersion": model_version,
        "trainingRows": training_rows,
        "baselineRows": baseline_rows,
        "stationCount": station_count,
        "trainingStart": training_start,
        "trainingEnd": training_end,
    }


def _slot_prediction(
    db: sqlite3.Connection,
    station_id: str,
    moment: datetime,
    model_version: str,
) -> tuple[float, float, str]:
    weekday, minute = moment.weekday(), moment.hour * 60 + (moment.minute // 5) * 5
    row = db.execute(
        """
        SELECT expected_rentals, expected_returns
        FROM baseline_5m
        WHERE model_version=? AND station_id=? AND weekday=? AND minute_of_day=?
        """,
        (model_version, station_id, weekday, minute),
    ).fetchone()
    if row:
        return float(row[0]), float(row[1]), "station-weekday"
    row = db.execute(
        """
        SELECT sum(expected_rentals * sample_count) / sum(sample_count),
               sum(expected_returns * sample_count) / sum(sample_count)
        FROM baseline_5m
        WHERE model_version=? AND station_id=? AND minute_of_day=?
        """,
        (model_version, station_id, minute),
    ).fetchone()
    if row and row[0] is not None:
        return float(row[0]), float(row[1]), "station-time"
    return 0.0, 0.0, "zero"


def predict_30m(
    db: sqlite3.Connection,
    station_id: str,
    as_of: datetime,
    *,
    model_version: str = MODEL_VERSION,
) -> dict[str, float | str | list[str]]:
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=KST)
    else:
        as_of = as_of.astimezone(KST)
    slot = as_of.replace(minute=(as_of.minute // 5) * 5, second=0, microsecond=0)
    rentals = returns = 0.0
    levels: list[str] = []
    for offset in range(0, 30, 5):
        predicted_rentals, predicted_returns, level = _slot_prediction(
            db, station_id, slot + timedelta(minutes=offset), model_version
        )
        rentals += predicted_rentals
        returns += predicted_returns
        levels.append(level)
    return {
        "stationId": station_id,
        "asOf": slot.isoformat(),
        "horizonMinutes": 30,
        "expectedRentals30m": round(rentals, 3),
        "expectedReturns30m": round(returns, 3),
        "modelVersion": model_version,
        "fallbackLevels": levels,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train or query the historical mean baseline.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--predict-station")
    parser.add_argument("--as-of", help="ISO datetime; defaults to now in KST")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with connect(args.db) as db:
        if args.predict_station:
            ensure_baseline_schema(db)
            moment = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(KST)
            print(predict_30m(db, args.predict_station, moment, model_version=args.model_version))
        else:
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
