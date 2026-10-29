"""Evaluate 30-minute inventory forecasts against collected API snapshots."""

from __future__ import annotations

import argparse
import csv
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3

from backend.api import DEFAULT_DB_PATH, DEFAULT_PREDICTION_DB_PATH, MODEL_VERSION
from backend.evaluate_baseline import Metrics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "inventory-evaluation"
KST = timezone(timedelta(hours=9))
STATUSES = ("shortage", "normal", "surplus")


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=60
    )
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _load_model(
    path: Path, model_version: str
) -> tuple[dict[tuple[str, int, int], tuple[float, float]], dict]:
    with closing(_read_only(path)) as db:
        metadata = db.execute(
            """
            SELECT model_version, trained_at, training_start, training_end,
                   training_rows, station_count
            FROM baseline_models WHERE model_version=?
            """,
            (model_version,),
        ).fetchone()
        if metadata is None:
            raise ValueError(f"model not found: {model_version}")
        predictions = {
            (str(station_id), int(weekday), int(minute)): (
                float(expected_rentals),
                float(expected_returns),
            )
            for station_id, weekday, minute, expected_rentals, expected_returns in db.execute(
                """
                SELECT station_id, weekday, minute_of_day,
                       expected_rentals, expected_returns
                FROM baseline_5m WHERE model_version=?
                """,
                (model_version,),
            )
        }
    fields = (
        "modelVersion",
        "trainedAt",
        "trainingStart",
        "trainingEnd",
        "trainingRows",
        "stationCount",
    )
    return predictions, dict(zip(fields, metadata))


def _prediction_30m(
    model: dict[tuple[str, int, int], tuple[float, float]],
    station_id: str,
    origin: datetime,
) -> tuple[float, float] | None:
    moment = origin.astimezone(KST)
    rentals = returns = 0.0
    for offset in range(0, 30, 5):
        target = moment + timedelta(minutes=offset)
        values = model.get((station_id, target.weekday(), target.hour * 60 + target.minute))
        if values is None:
            return None
        rentals += values[0]
        returns += values[1]
    return rentals, returns


def _status(bikes: float, capacity: int) -> str | None:
    if capacity <= 0:
        return None
    ratio = bikes / capacity
    if ratio <= 0.2:
        return "shortage"
    if ratio >= 0.8:
        return "surplus"
    return "normal"


def _time_bucket(moment: datetime) -> str:
    minute = moment.astimezone(KST).hour * 60 + moment.astimezone(KST).minute
    if 420 <= minute < 600:
        return "morning-commute"
    if 600 <= minute < 1020:
        return "daytime"
    if 1020 <= minute < 1260:
        return "evening-commute"
    return "night"


class Confusion:
    def __init__(self) -> None:
        self.values = {(actual, predicted): 0 for actual in STATUSES for predicted in STATUSES}

    def add(self, actual: str, predicted: str) -> None:
        self.values[(actual, predicted)] += 1

    def as_dict(self) -> dict:
        total = sum(self.values.values())
        correct = sum(self.values[(status, status)] for status in STATUSES)
        per_status = {}
        for status in STATUSES:
            true_positive = self.values[(status, status)]
            predicted_count = sum(self.values[(actual, status)] for actual in STATUSES)
            actual_count = sum(self.values[(status, predicted)] for predicted in STATUSES)
            precision = true_positive / predicted_count if predicted_count else None
            recall = true_positive / actual_count if actual_count else None
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision is not None and recall is not None and precision + recall
                else None
            )
            per_status[status] = {
                "support": actual_count,
                "precision": round(precision, 6) if precision is not None else None,
                "recall": round(recall, 6) if recall is not None else None,
                "f1": round(f1, 6) if f1 is not None else None,
            }
        f1_values = [value["f1"] for value in per_status.values() if value["f1"] is not None]
        return {
            "samples": total,
            "accuracy": round(correct / total, 6) if total else None,
            "macroF1": round(sum(f1_values) / len(f1_values), 6) if f1_values else None,
            "perStatus": per_status,
            "matrix": {
                actual: {predicted: self.values[(actual, predicted)] for predicted in STATUSES}
                for actual in STATUSES
            },
        }


def _binary_event(actual: bool, predicted: bool, values: dict[str, int]) -> None:
    if actual and predicted:
        values["truePositive"] += 1
    elif actual:
        values["falseNegative"] += 1
    elif predicted:
        values["falsePositive"] += 1
    else:
        values["trueNegative"] += 1


def _binary_result(values: dict[str, int]) -> dict:
    tp, fp, fn = values["truePositive"], values["falsePositive"], values["falseNegative"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        **values,
        "precision": round(precision, 6) if precision is not None else None,
        "recall": round(recall, 6) if recall is not None else None,
        "f1": round(f1, 6) if f1 is not None else None,
    }


def _metric_row(group: str, model: str, metrics: Metrics) -> dict:
    return {"group": group, "model": model, **metrics.as_dict()}


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate(
    inventory_path: Path,
    prediction_path: Path,
    output_dir: Path,
    *,
    model_version: str = MODEL_VERSION,
    include_training_period: bool = False,
) -> dict:
    model, metadata = _load_model(prediction_path, model_version)
    model_stations = {key[0] for key in model}
    training_end = metadata["trainingEnd"]
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_metrics = {"zero-change": Metrics(), "seasonal-mean": Metrics()}
    clipped_metrics = {"zero-change": Metrics(), "seasonal-mean": Metrics()}
    by_time: dict[tuple[str, str], Metrics] = {}
    by_station: dict[tuple[str, str], Metrics] = {}
    status_confusions = {"zero-change": Confusion(), "seasonal-mean": Confusion()}
    stockout = {
        model_name: {key: 0 for key in ("truePositive", "falsePositive", "falseNegative", "trueNegative")}
        for model_name in ("zero-change", "seasonal-mean")
    }
    full = {
        model_name: {key: 0 for key in ("truePositive", "falsePositive", "falseNegative", "trueNegative")}
        for model_name in ("zero-change", "seasonal-mean")
    }
    slot_pairs = evaluated_pairs = missing_model = invalid_capacity = 0
    evaluated_stations: set[str] = set()
    used_origins: list[datetime] = []

    with closing(_read_only(inventory_path)) as db:
        slots = [
            (datetime.fromisoformat(slot), str(run_id))
            for slot, run_id in db.execute("SELECT slot, run_id FROM slots ORDER BY slot")
        ]
        run_by_time = {moment: run_id for moment, run_id in slots}
        origins = [moment for moment, _run_id in slots if moment + timedelta(minutes=30) in run_by_time]
        for origin in origins:
            if not include_training_period and origin.astimezone(KST).date().isoformat() <= training_end:
                continue
            slot_pairs += 1
            origin_run = run_by_time[origin]
            target_run = run_by_time[origin + timedelta(minutes=30)]
            rows = db.execute(
                """
                SELECT current.station_id, current.rack_count, current.current_bikes,
                       future.current_bikes
                FROM observations current
                JOIN observations future ON future.station_id=current.station_id
                WHERE current.run_id=? AND future.run_id=?
                """,
                (origin_run, target_run),
            )
            origin_used = False
            for station_id, capacity, current_bikes, actual_bikes in rows:
                station_id = str(station_id)
                if station_id not in model_stations:
                    continue
                prediction = _prediction_30m(model, station_id, origin)
                if prediction is None:
                    missing_model += 1
                    continue
                capacity = int(capacity)
                if capacity <= 0:
                    invalid_capacity += 1
                    continue
                expected_rentals, expected_returns = prediction
                predictions = {
                    "zero-change": float(current_bikes),
                    "seasonal-mean": float(current_bikes) + expected_returns - expected_rentals,
                }
                actual_bikes = float(actual_bikes)
                bucket = _time_bucket(origin)
                actual_status = _status(actual_bikes, capacity)
                for model_name, predicted_bikes in predictions.items():
                    raw_metrics[model_name].add(actual_bikes, predicted_bikes)
                    clipped = min(float(capacity), max(0.0, predicted_bikes))
                    clipped_metrics[model_name].add(actual_bikes, clipped)
                    by_time.setdefault((bucket, model_name), Metrics()).add(
                        actual_bikes, predicted_bikes
                    )
                    by_station.setdefault((station_id, model_name), Metrics()).add(
                        actual_bikes, predicted_bikes
                    )
                    predicted_status = _status(predicted_bikes, capacity)
                    assert actual_status is not None and predicted_status is not None
                    status_confusions[model_name].add(actual_status, predicted_status)
                    _binary_event(actual_bikes <= 0, predicted_bikes <= 0, stockout[model_name])
                    _binary_event(
                        actual_bikes >= capacity, predicted_bikes >= capacity, full[model_name]
                    )
                evaluated_pairs += 1
                evaluated_stations.add(station_id)
                origin_used = True
            if origin_used:
                used_origins.append(origin)

    overall_rows = [
        _metric_row("all", model_name, raw_metrics[model_name])
        for model_name in ("zero-change", "seasonal-mean")
    ]
    clipped_rows = [
        _metric_row("all", model_name, clipped_metrics[model_name])
        for model_name in ("zero-change", "seasonal-mean")
    ]
    time_rows = [
        _metric_row(bucket, model_name, metrics)
        for (bucket, model_name), metrics in sorted(by_time.items())
    ]
    station_rows = [
        _metric_row(station_id, model_name, metrics)
        for (station_id, model_name), metrics in sorted(by_station.items())
    ]
    result = {
        "evaluationVersion": "inventory-backtest-v1",
        "inventoryDatabase": str(inventory_path.resolve()),
        "predictionDatabase": str(prediction_path.resolve()),
        "model": metadata,
        "trainingPeriodPairsIncluded": include_training_period,
        "inventoryRange": {
            "start": slots[0][0].isoformat() if slots else None,
            "end": slots[-1][0].isoformat() if slots else None,
        },
        "evaluatedOriginRange": {
            "start": min(used_origins).isoformat() if used_origins else None,
            "end": max(used_origins).isoformat() if used_origins else None,
        },
        "counts": {
            "successfulSlots": len(slots),
            "allExact30MinuteSlotPairs": len(origins),
            "excludedTrainingPeriodPairs": len(origins) - slot_pairs,
            "eligible30MinuteSlotPairs": slot_pairs,
            "stationForecasts": evaluated_pairs,
            "stations": len(evaluated_stations),
            "missingModelRows": missing_model,
            "invalidCapacityRows": invalid_capacity,
        },
        "inventoryMetrics": {
            model_name: raw_metrics[model_name].as_dict()
            for model_name in ("zero-change", "seasonal-mean")
        },
        "clippedInventoryMetrics": {
            model_name: clipped_metrics[model_name].as_dict()
            for model_name in ("zero-change", "seasonal-mean")
        },
        "statusClassification": {
            model_name: status_confusions[model_name].as_dict()
            for model_name in ("zero-change", "seasonal-mean")
        },
        "hardEvents": {
            "stockout": {
                model_name: _binary_result(stockout[model_name])
                for model_name in ("zero-change", "seasonal-mean")
            },
            "fullStation": {
                model_name: _binary_result(full[model_name])
                for model_name in ("zero-change", "seasonal-mean")
            },
        },
        "notes": [
            "Only exact t and t+30-minute successful inventory snapshots are paired.",
            "Origins on or before the model training end date are excluded by default to prevent leakage.",
            "zero-change predicts that the current inventory remains unchanged.",
            "seasonal-mean mirrors the dashboard formula: current + expected returns - expected rentals.",
            "Observed inventory can include operator rebalancing, maintenance, and collection timing differences in addition to customer flows.",
        ],
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(output_dir / "overall.csv", overall_rows)
    _write_csv(output_dir / "overall_clipped.csv", clipped_rows)
    _write_csv(output_dir / "by_time_bucket.csv", time_rows)
    _write_csv(output_dir / "by_station.csv", station_rows)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--prediction-db", type=Path, default=DEFAULT_PREDICTION_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--model-version", default=MODEL_VERSION)
    parser.add_argument(
        "--include-training-period",
        action="store_true",
        help="also evaluate origins on/before training_end (normally excluded as leakage)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate(
        args.inventory_db,
        args.prediction_db,
        args.output_dir,
        model_version=args.model_version,
        include_training_period=args.include_training_period,
    )
    print(json.dumps({
        "counts": result["counts"],
        "evaluatedOriginRange": result["evaluatedOriginRange"],
        "inventoryMetrics": result["inventoryMetrics"],
        "statusClassification": result["statusClassification"],
        "outputDir": str(args.output_dir.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
