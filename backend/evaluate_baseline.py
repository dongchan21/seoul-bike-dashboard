"""Time-ordered backtest for 30-minute station-flow baselines.

The evaluator never writes to the source database.  It learns every statistic
from the training period only, then evaluates validation and test periods on a
common set of 30-minute windows.
"""

from __future__ import annotations

import argparse
import csv
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator

from backend.prepare_gangnam_year import DEFAULT_DB


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "baseline-evaluation"
MODELS = ("zero-flow", "recent-30m", "seasonal-mean")
TARGETS = ("rentals30m", "returns30m", "stockChange30m")


@dataclass
class Metrics:
    count: int = 0
    absolute_error: float = 0.0
    squared_error: float = 0.0
    absolute_actual: float = 0.0
    actual_total: float = 0.0
    predicted_total: float = 0.0

    def add(self, actual: float, predicted: float) -> None:
        error = predicted - actual
        self.count += 1
        self.absolute_error += abs(error)
        self.squared_error += error * error
        self.absolute_actual += abs(actual)
        self.actual_total += actual
        self.predicted_total += predicted

    def as_dict(self) -> dict[str, int | float | None]:
        if not self.count:
            return {
                "samples": 0,
                "mae": None,
                "rmse": None,
                "wape": None,
                "actualMean": None,
                "predictedMean": None,
            }
        return {
            "samples": self.count,
            "mae": round(self.absolute_error / self.count, 6),
            "rmse": round(math.sqrt(self.squared_error / self.count), 6),
            "wape": (
                round(self.absolute_error / self.absolute_actual, 6)
                if self.absolute_actual
                else None
            ),
            "actualMean": round(self.actual_total / self.count, 6),
            "predictedMean": round(self.predicted_total / self.count, 6),
        }


def _date_bounds(db: sqlite3.Connection) -> tuple[str, str]:
    row = db.execute(
        "SELECT min(min_date), max(max_date) FROM flow_imports WHERE station_days > 0"
    ).fetchone()
    if not row or not row[0] or not row[1]:
        row = db.execute("SELECT min(service_date), max(service_date) FROM flows_5m").fetchone()
    if not row or not row[0] or not row[1]:
        raise ValueError("flows_5m has no data")
    return str(row[0]), str(row[1])


def default_splits(min_date: str, max_date: str) -> dict[str, str]:
    """Split a calendar range into approximately 8/2/2 months."""
    start, end = date.fromisoformat(min_date), date.fromisoformat(max_date)
    days = (end - start).days + 1
    if days < 12:
        raise ValueError("at least 12 calendar days are required for a three-way split")
    train_days = round(days * 2 / 3)
    validation_days = round(days / 6)
    train_end = start + timedelta(days=train_days - 1)
    validation_start = train_end + timedelta(days=1)
    validation_end = validation_start + timedelta(days=validation_days - 1)
    test_start = validation_end + timedelta(days=1)
    return {
        "trainStart": start.isoformat(),
        "trainEnd": train_end.isoformat(),
        "validationStart": validation_start.isoformat(),
        "validationEnd": validation_end.isoformat(),
        "testStart": test_start.isoformat(),
        "testEnd": end.isoformat(),
    }


def _validate_splits(splits: dict[str, str]) -> None:
    ordered = [
        splits["trainStart"],
        splits["trainEnd"],
        splits["validationStart"],
        splits["validationEnd"],
        splits["testStart"],
        splits["testEnd"],
    ]
    for value in ordered:
        date.fromisoformat(value)
    if not (
        ordered[0] <= ordered[1]
        < ordered[2] <= ordered[3]
        < ordered[4] <= ordered[5]
    ):
        raise ValueError("periods must be non-overlapping and ordered train -> validation -> test")


def _learn_seasonal_means(
    db: sqlite3.Connection, start: str, end: str
) -> tuple[
    dict[tuple[str, int, int], tuple[float, float]],
    dict[tuple[str, int], tuple[float, float]],
    dict[str, int],
]:
    station_weekday: dict[tuple[str, int, int], list[float]] = {}
    station_time: dict[tuple[str, int], list[float]] = {}
    day_cache: dict[str, int] = {}
    station_ids: set[str] = set()
    rows = 0
    cursor = db.execute(
        """
        SELECT station_id, service_date, minute_of_day, rentals, returns
        FROM flows_5m
        WHERE service_date BETWEEN ? AND ?
        ORDER BY station_id, service_date, minute_of_day
        """,
        (start, end),
    )
    for station_id, service_date, minute, rentals, returns_ in cursor:
        station_id = str(station_id)
        station_ids.add(station_id)
        service_date = str(service_date)
        weekday = day_cache.get(service_date)
        if weekday is None:
            weekday = date.fromisoformat(service_date).weekday()
            day_cache[service_date] = weekday
        weekday_key = (station_id, weekday, int(minute))
        time_key = (station_id, int(minute))
        weekday_value = station_weekday.setdefault(weekday_key, [0.0, 0.0, 0.0])
        weekday_value[0] += int(rentals)
        weekday_value[1] += int(returns_)
        weekday_value[2] += 1
        time_value = station_time.setdefault(time_key, [0.0, 0.0, 0.0])
        time_value[0] += int(rentals)
        time_value[1] += int(returns_)
        time_value[2] += 1
        rows += 1

    if not rows:
        raise ValueError("training period has no flows_5m rows")

    def means(values: dict[tuple, list[float]]) -> dict[tuple, tuple[float, float]]:
        return {
            key: (value[0] / value[2], value[1] / value[2])
            for key, value in values.items()
        }

    return means(station_weekday), means(station_time), {
        "rows": rows,
        "stations": len(station_ids),
        "stationWeekdaySlots": len(station_weekday),
        "stationTimeSlots": len(station_time),
    }


def _station_days(
    db: sqlite3.Connection, start: str, end: str
) -> Iterator[tuple[str, str, list[int], list[int]]]:
    cursor = db.execute(
        """
        SELECT station_id, service_date, minute_of_day, rentals, returns
        FROM flows_5m
        WHERE service_date BETWEEN ? AND ?
        ORDER BY station_id, service_date, minute_of_day
        """,
        (start, end),
    )
    current: tuple[str, str] | None = None
    rentals = [0] * 288
    returns = [0] * 288
    seen: set[int] = set()
    for station_id, service_date, minute, rental_count, return_count in cursor:
        key = str(station_id), str(service_date)
        if current is not None and key != current:
            if len(seen) == 288:
                yield current[0], current[1], rentals, returns
            rentals, returns, seen = [0] * 288, [0] * 288, set()
        current = key
        index = int(minute) // 5
        if 0 <= index < 288:
            rentals[index] = int(rental_count)
            returns[index] = int(return_count)
            seen.add(index)
    if current is not None and len(seen) == 288:
        yield current[0], current[1], rentals, returns


def _time_bucket(minute: int) -> str:
    if 420 <= minute < 600:
        return "morning-commute"
    if 600 <= minute < 1020:
        return "daytime"
    if 1020 <= minute < 1260:
        return "evening-commute"
    return "night"


def _add_targets(
    target_metrics: dict[str, Metrics],
    actual_rentals: float,
    actual_returns: float,
    predicted_rentals: float,
    predicted_returns: float,
) -> None:
    target_metrics["rentals30m"].add(actual_rentals, predicted_rentals)
    target_metrics["returns30m"].add(actual_returns, predicted_returns)
    target_metrics["stockChange30m"].add(
        actual_returns - actual_rentals,
        predicted_returns - predicted_rentals,
    )


def _new_target_metrics() -> dict[str, Metrics]:
    return {target: Metrics() for target in TARGETS}


def _evaluate_period(
    db: sqlite3.Connection,
    *,
    split: str,
    start: str,
    end: str,
    station_weekday: dict[tuple[str, int, int], tuple[float, float]],
    station_time: dict[tuple[str, int], tuple[float, float]],
    overall: dict[tuple[str, str], dict[str, Metrics]],
    by_time: dict[tuple[str, str, str], dict[str, Metrics]],
    by_station: dict[tuple[str, str, str], dict[str, Metrics]],
    coverage: dict[str, int],
    origin_step_minutes: int,
) -> dict[str, int]:
    station_days = windows = skipped_days = 0
    for station_id, service_date, rentals, returns in _station_days(db, start, end):
        station_days += 1
        weekday = date.fromisoformat(service_date).weekday()
        rental_prefix = [0]
        return_prefix = [0]
        for value in rentals:
            rental_prefix.append(rental_prefix[-1] + value)
        for value in returns:
            return_prefix.append(return_prefix[-1] + value)

        overall_sets = {
            model: overall.setdefault((split, model), _new_target_metrics())
            for model in MODELS
        }
        time_sets = {
            (model, bucket): by_time.setdefault(
                (split, model, bucket), _new_target_metrics()
            )
            for model in MODELS
            for bucket in ("morning-commute", "daytime", "evening-commute", "night")
        }
        station_sets = {
            model: by_station.setdefault(
                (split, model, station_id), _new_target_metrics()
            )
            for model in MODELS
        }

        # All models use identical windows: six previous slots are available,
        # and the six target slots do not cross midnight.
        for index in range(6, 283, origin_step_minutes // 5):
            actual_rentals = rental_prefix[index + 6] - rental_prefix[index]
            actual_returns = return_prefix[index + 6] - return_prefix[index]
            recent_rentals = rental_prefix[index] - rental_prefix[index - 6]
            recent_returns = return_prefix[index] - return_prefix[index - 6]
            seasonal_rentals = seasonal_returns = 0.0
            for target_index in range(index, index + 6):
                minute = target_index * 5
                prediction = station_weekday.get((station_id, weekday, minute))
                if prediction is not None:
                    coverage["stationWeekdaySlots"] += 1
                else:
                    prediction = station_time.get((station_id, minute))
                    if prediction is not None:
                        coverage["stationTimeFallbackSlots"] += 1
                    else:
                        prediction = (0.0, 0.0)
                        coverage["zeroFallbackSlots"] += 1
                seasonal_rentals += prediction[0]
                seasonal_returns += prediction[1]

            predictions = {
                "zero-flow": (0.0, 0.0),
                "recent-30m": (float(recent_rentals), float(recent_returns)),
                "seasonal-mean": (seasonal_rentals, seasonal_returns),
            }
            bucket = _time_bucket(index * 5)
            for model, (predicted_rentals, predicted_returns) in predictions.items():
                _add_targets(
                    overall_sets[model],
                    actual_rentals,
                    actual_returns,
                    predicted_rentals,
                    predicted_returns,
                )
                _add_targets(
                    time_sets[(model, bucket)],
                    actual_rentals,
                    actual_returns,
                    predicted_rentals,
                    predicted_returns,
                )
                _add_targets(
                    station_sets[model],
                    actual_rentals,
                    actual_returns,
                    predicted_rentals,
                    predicted_returns,
                )
            windows += 1
    return {"stationDays": station_days, "windows": windows, "skippedDays": skipped_days}


def _metric_rows(
    values: dict[tuple, dict[str, Metrics]], columns: tuple[str, ...]
) -> list[dict[str, str | int | float | None]]:
    rows: list[dict[str, str | int | float | None]] = []
    for key in sorted(values):
        labels = dict(zip(columns, key))
        for target in TARGETS:
            rows.append({**labels, "target": target, **values[key][target].as_dict()})
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(
    db_path: Path,
    output_dir: Path,
    splits: dict[str, str] | None = None,
    origin_step_minutes: int = 30,
) -> dict:
    if origin_step_minutes <= 0 or origin_step_minutes % 5:
        raise ValueError("origin_step_minutes must be a positive multiple of 5")
    output_dir.mkdir(parents=True, exist_ok=True)
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=60)) as db:
        db.execute("PRAGMA query_only=ON")
        source_min, source_max = _date_bounds(db)
        periods = splits or default_splits(source_min, source_max)
        _validate_splits(periods)
        seasonal_weekday, seasonal_time, training = _learn_seasonal_means(
            db, periods["trainStart"], periods["trainEnd"]
        )
        overall: dict[tuple[str, str], dict[str, Metrics]] = {}
        by_time: dict[tuple[str, str, str], dict[str, Metrics]] = {}
        by_station: dict[tuple[str, str, str], dict[str, Metrics]] = {}
        coverage = {
            "stationWeekdaySlots": 0,
            "stationTimeFallbackSlots": 0,
            "zeroFallbackSlots": 0,
        }
        period_stats = {}
        for split in ("validation", "test"):
            period_stats[split] = _evaluate_period(
                db,
                split=split,
                start=periods[f"{split}Start"],
                end=periods[f"{split}End"],
                station_weekday=seasonal_weekday,
                station_time=seasonal_time,
                overall=overall,
                by_time=by_time,
                by_station=by_station,
                coverage=coverage,
                origin_step_minutes=origin_step_minutes,
            )

    overall_rows = _metric_rows(overall, ("split", "model"))
    time_rows = _metric_rows(by_time, ("split", "model", "timeBucket"))
    station_rows = _metric_rows(by_station, ("split", "model", "stationId"))
    result = {
        "evaluationVersion": "baseline-backtest-v1",
        "sourceDatabase": str(db_path.resolve()),
        "sourceRange": {"start": source_min, "end": source_max},
        "periods": periods,
        "training": training,
        "periodStats": period_stats,
        "originStepMinutes": origin_step_minutes,
        "coverage": coverage,
        "models": {
            "zero-flow": "predicts zero rentals and returns",
            "recent-30m": "repeats the immediately preceding 30-minute totals",
            "seasonal-mean": "training-period station + weekday + 5-minute mean",
        },
        "targets": {
            "rentals30m": "actual versus predicted rentals in the next 30 minutes",
            "returns30m": "actual versus predicted returns in the next 30 minutes",
            "stockChange30m": "returns minus rentals; not an observed inventory snapshot",
        },
        "metrics": {"overall": overall_rows},
        "notes": [
            f"All models are evaluated on the same windows from 00:30 through 23:30 at {origin_step_minutes}-minute origin intervals.",
            "Training statistics never use validation or test rows.",
            "stockChange30m measures flow-implied inventory change. Absolute observed inventory evaluation is a separate step using paired real-time snapshots.",
        ],
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(output_dir / "overall.csv", overall_rows)
    _write_csv(output_dir / "by_time_bucket.csv", time_rows)
    _write_csv(output_dir / "by_station.csv", station_rows)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-start")
    parser.add_argument("--train-end")
    parser.add_argument("--validation-start")
    parser.add_argument("--validation-end")
    parser.add_argument("--test-start")
    parser.add_argument("--test-end")
    parser.add_argument(
        "--origin-step-minutes",
        type=int,
        default=30,
        help="forecast-origin interval; 30 avoids heavily overlapping evaluation windows",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    custom = [
        args.train_start,
        args.train_end,
        args.validation_start,
        args.validation_end,
        args.test_start,
        args.test_end,
    ]
    if any(custom) and not all(custom):
        raise SystemExit("when overriding periods, provide all six start/end arguments")
    splits = None
    if all(custom):
        splits = {
            "trainStart": args.train_start,
            "trainEnd": args.train_end,
            "validationStart": args.validation_start,
            "validationEnd": args.validation_end,
            "testStart": args.test_start,
            "testEnd": args.test_end,
        }
    result = evaluate(args.db, args.output_dir, splits, args.origin_step_minutes)
    print(json.dumps({
        "periods": result["periods"],
        "training": result["training"],
        "periodStats": result["periodStats"],
        "outputDir": str(args.output_dir.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
