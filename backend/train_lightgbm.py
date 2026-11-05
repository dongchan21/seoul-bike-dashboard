"""Train and evaluate a deployable calendar-feature LightGBM baseline."""

from __future__ import annotations

import argparse
import csv
from contextlib import closing
from datetime import date
import json
import math
from pathlib import Path
import sqlite3

from backend.evaluate_baseline import _date_bounds, _station_days, default_splits
from backend.prepare_gangnam_year import DEFAULT_DB


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_DIR = ROOT / "models" / "calendar-lightgbm-v1"
DEFAULT_REPORT_DIR = ROOT / "reports" / "calendar-lightgbm-v1"
MODEL_VERSION = "calendar-lightgbm-v1"
FEATURE_NAMES = (
    "stationId",
    "weekday",
    "originSlot",
    "month",
    "dayOfYearSin",
    "dayOfYearCos",
    "isWeekend",
    "isHoliday",
    "commuteType",
)
CATEGORICAL_FEATURES = (
    "stationId",
    "weekday",
    "originSlot",
    "month",
    "isWeekend",
    "isHoliday",
    "commuteType",
)
ORIGIN_INDEXES = tuple(range(6, 283, 6))


def _imports():
    try:
        import holidays
        import lightgbm as lgb
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "ML dependencies are missing; run: "
            ".\\.venv\\Scripts\\python.exe -m pip install -r backend\\requirements-ml.txt"
        ) from exc
    return holidays, lgb, np


def _read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=60
    )
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _split_for_day(day: str, splits: dict[str, str]) -> str | None:
    if splits["trainStart"] <= day <= splits["trainEnd"]:
        return "train"
    if splits["validationStart"] <= day <= splits["validationEnd"]:
        return "validation"
    if splits["testStart"] <= day <= splits["testEnd"]:
        return "test"
    return None


def _commute_type(minute: int) -> int:
    if 420 <= minute < 600:
        return 1
    if 1020 <= minute < 1260:
        return 2
    return 0


def _station_mapping(db: sqlite3.Connection) -> dict[str, int]:
    rows = db.execute(
        """
        SELECT station_id FROM station_master
        WHERE district='강남구'
        ORDER BY station_id
        """
    ).fetchall()
    if not rows:
        rows = db.execute("SELECT DISTINCT station_id FROM flows_5m ORDER BY station_id").fetchall()
    return {str(row[0]): index for index, row in enumerate(rows)}


def _sample_counts(db: sqlite3.Connection, splits: dict[str, str]) -> dict[str, int]:
    counts = {}
    for split in ("train", "validation", "test"):
        start = splits[f"{split}Start"]
        end = splits[f"{split}End"]
        rows = db.execute(
            "SELECT count(*) FROM flows_5m WHERE service_date BETWEEN ? AND ?",
            (start, end),
        ).fetchone()[0]
        if rows % 288:
            raise ValueError(f"{split} has incomplete dense station-days: {rows} rows")
        counts[split] = rows // 288 * len(ORIGIN_INDEXES)
    return counts


def build_datasets(db_path: Path, splits: dict[str, str] | None = None):
    holidays, _lgb, np = _imports()
    with closing(_read_only(db_path)) as db:
        source_start, source_end = _date_bounds(db)
        periods = splits or default_splits(source_start, source_end)
        station_map = _station_mapping(db)
        counts = _sample_counts(db, periods)
        datasets = {
            split: {
                "X": np.empty((count, len(FEATURE_NAMES)), dtype=np.float32),
                "rentals": np.empty(count, dtype=np.float32),
                "returns": np.empty(count, dtype=np.float32),
                "position": 0,
            }
            for split, count in counts.items()
        }
        years = range(date.fromisoformat(source_start).year, date.fromisoformat(source_end).year + 1)
        korean_holidays = holidays.KR(years=years)
        origin_indexes = np.asarray(ORIGIN_INDEXES, dtype=np.int16)
        origin_minutes = origin_indexes * 5
        origin_slots = origin_minutes // 30
        commute = np.asarray([_commute_type(int(value)) for value in origin_minutes])

        for station_id, service_date, rentals, returns in _station_days(
            db, source_start, source_end
        ):
            split = _split_for_day(service_date, periods)
            if split is None:
                continue
            data = datasets[split]
            start = data["position"]
            end = start + len(ORIGIN_INDEXES)
            day = date.fromisoformat(service_date)
            day_angle = 2 * math.pi * day.timetuple().tm_yday / 366
            station_code = station_map.get(station_id, -1)
            block = data["X"][start:end]
            block[:, 0] = station_code
            block[:, 1] = day.weekday()
            block[:, 2] = origin_slots
            block[:, 3] = day.month
            block[:, 4] = math.sin(day_angle)
            block[:, 5] = math.cos(day_angle)
            block[:, 6] = int(day.weekday() >= 5)
            block[:, 7] = int(day in korean_holidays)
            block[:, 8] = commute
            rental_prefix = np.concatenate((np.zeros(1, dtype=np.int32), np.cumsum(rentals)))
            return_prefix = np.concatenate((np.zeros(1, dtype=np.int32), np.cumsum(returns)))
            data["rentals"][start:end] = (
                rental_prefix[origin_indexes + 6] - rental_prefix[origin_indexes]
            )
            data["returns"][start:end] = (
                return_prefix[origin_indexes + 6] - return_prefix[origin_indexes]
            )
            data["position"] = end

    for split, data in datasets.items():
        position = data.pop("position")
        if position != counts[split]:
            data["X"] = data["X"][:position]
            data["rentals"] = data["rentals"][:position]
            data["returns"] = data["returns"][:position]
            counts[split] = position
    return datasets, periods, station_map, counts


def _metrics(np, actual, predicted) -> dict:
    error = predicted - actual
    absolute = np.abs(error)
    denominator = float(np.abs(actual).sum())
    return {
        "samples": int(actual.size),
        "mae": round(float(absolute.mean()), 6),
        "rmse": round(float(np.sqrt(np.mean(error * error))), 6),
        "wape": round(float(absolute.sum()) / denominator, 6) if denominator else None,
        "actualMean": round(float(actual.mean()), 6),
        "predictedMean": round(float(predicted.mean()), 6),
    }


def _seasonal_predictions(np, train, target_name: str, evaluate):
    train_x, train_y = train["X"], train[target_name]
    station_count = int(max(train_x[:, 0].max(), evaluate["X"][:, 0].max())) + 2
    max_code = station_count * 7 * 48
    train_codes = (
        train_x[:, 0].astype(np.int64) * 7 * 48
        + train_x[:, 1].astype(np.int64) * 48
        + train_x[:, 2].astype(np.int64)
    )
    sums = np.bincount(train_codes, weights=train_y, minlength=max_code)
    counts = np.bincount(train_codes, minlength=max_code)
    station_slot_codes = train_x[:, 0].astype(np.int64) * 48 + train_x[:, 2].astype(np.int64)
    fallback_size = station_count * 48
    fallback_sums = np.bincount(station_slot_codes, weights=train_y, minlength=fallback_size)
    fallback_counts = np.bincount(station_slot_codes, minlength=fallback_size)
    eval_x = evaluate["X"]
    eval_codes = (
        eval_x[:, 0].astype(np.int64) * 7 * 48
        + eval_x[:, 1].astype(np.int64) * 48
        + eval_x[:, 2].astype(np.int64)
    )
    fallback_codes = eval_x[:, 0].astype(np.int64) * 48 + eval_x[:, 2].astype(np.int64)
    predictions = np.zeros(eval_x.shape[0], dtype=np.float64)
    exact = counts[eval_codes] > 0
    predictions[exact] = sums[eval_codes[exact]] / counts[eval_codes[exact]]
    fallback = ~exact & (fallback_counts[fallback_codes] > 0)
    predictions[fallback] = (
        fallback_sums[fallback_codes[fallback]] / fallback_counts[fallback_codes[fallback]]
    )
    return predictions


def _train_one(lgb, train, validation, target: str, rounds: int, early_stopping: int):
    train_set = lgb.Dataset(
        train["X"],
        label=train[target],
        feature_name=list(FEATURE_NAMES),
        categorical_feature=list(CATEGORICAL_FEATURES),
        free_raw_data=False,
    )
    validation_set = lgb.Dataset(
        validation["X"],
        label=validation[target],
        reference=train_set,
        feature_name=list(FEATURE_NAMES),
        categorical_feature=list(CATEGORICAL_FEATURES),
        free_raw_data=False,
    )
    params = {
        "objective": "poisson",
        "metric": ["l1", "l2"],
        "learning_rate": 0.05,
        "num_leaves": 31,
        "min_data_in_leaf": 100,
        "feature_fraction": 0.9,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
        "max_bin": 127,
        "force_col_wise": True,
        "seed": 42,
        "verbosity": -1,
    }
    return lgb.train(
        params,
        train_set,
        num_boost_round=rounds,
        valid_sets=[validation_set],
        valid_names=["validation"],
        callbacks=[
            lgb.early_stopping(early_stopping, verbose=True),
            lgb.log_evaluation(25),
        ],
    )


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def train_and_evaluate(
    db_path: Path,
    model_dir: Path,
    report_dir: Path,
    *,
    rounds: int = 300,
    early_stopping: int = 30,
) -> dict:
    _holidays, lgb, np = _imports()
    datasets, periods, station_map, counts = build_datasets(db_path)
    model_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    models = {}
    for target in ("rentals", "returns"):
        print(f"Training {target} model on {counts['train']:,} samples...", flush=True)
        models[target] = _train_one(
            lgb,
            datasets["train"],
            datasets["validation"],
            target,
            rounds,
            early_stopping,
        )
        models[target].save_model(str(model_dir / f"{target}.txt"))

    rows = []
    predictions_by_split = {}
    for split in ("validation", "test"):
        data = datasets[split]
        zero = {
            "rentals": np.zeros(data["rentals"].shape[0]),
            "returns": np.zeros(data["returns"].shape[0]),
        }
        seasonal = {
            target: _seasonal_predictions(np, datasets["train"], target, data)
            for target in ("rentals", "returns")
        }
        machine = {
            target: np.maximum(
                0.0,
                models[target].predict(data["X"], num_iteration=models[target].best_iteration),
            )
            for target in ("rentals", "returns")
        }
        predictions_by_split[split] = machine
        for model_name, predicted in (
            ("zero-flow", zero),
            ("seasonal-mean", seasonal),
            (MODEL_VERSION, machine),
        ):
            for target in ("rentals", "returns"):
                rows.append(
                    {
                        "split": split,
                        "model": model_name,
                        "target": f"{target}30m",
                        **_metrics(np, data[target], predicted[target]),
                    }
                )
            actual_change = data["returns"] - data["rentals"]
            predicted_change = predicted["returns"] - predicted["rentals"]
            rows.append(
                {
                    "split": split,
                    "model": model_name,
                    "target": "stockChange30m",
                    **_metrics(np, actual_change, predicted_change),
                }
            )

    importance_rows = []
    for target, model in models.items():
        gains = model.feature_importance(importance_type="gain")
        total = float(gains.sum())
        for feature, gain in sorted(zip(FEATURE_NAMES, gains), key=lambda item: -item[1]):
            importance_rows.append(
                {
                    "target": target,
                    "feature": feature,
                    "gain": round(float(gain), 6),
                    "gainShare": round(float(gain) / total, 6) if total else 0.0,
                }
            )

    result = {
        "modelVersion": MODEL_VERSION,
        "sourceDatabase": str(db_path.resolve()),
        "periods": periods,
        "sampleCounts": counts,
        "stationMappingSize": len(station_map),
        "originStepMinutes": 30,
        "features": list(FEATURE_NAMES),
        "categoricalFeatures": list(CATEGORICAL_FEATURES),
        "targets": ["rentals30m", "returns30m"],
        "bestIterations": {target: model.best_iteration for target, model in models.items()},
        "metrics": rows,
        "featureImportance": importance_rows,
        "limitations": [
            "This first ML model uses only features available at prediction time: station and calendar variables.",
            "Current inventory is not a training feature because matching historical 5-minute inventory is unavailable.",
            "Weather and recent live inventory changes are reserved for later comparison models.",
        ],
    }
    (report_dir / "evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (model_dir / "metadata.json").write_text(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "modelVersion", "periods", "sampleCounts", "stationMappingSize",
                    "originStepMinutes", "features", "categoricalFeatures", "targets",
                    "bestIterations", "limitations",
                )
            }
            | {"stationMapping": station_map},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_csv(report_dir / "overall.csv", rows)
    _write_csv(report_dir / "feature_importance.csv", importance_rows)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--rounds", type=int, default=300)
    parser.add_argument("--early-stopping", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = train_and_evaluate(
        args.db,
        args.model_dir,
        args.report_dir,
        rounds=args.rounds,
        early_stopping=args.early_stopping,
    )
    test_rows = [row for row in result["metrics"] if row["split"] == "test"]
    print(json.dumps({
        "modelVersion": result["modelVersion"],
        "periods": result["periods"],
        "sampleCounts": result["sampleCounts"],
        "bestIterations": result["bestIterations"],
        "testMetrics": test_rows,
        "reportDir": str(args.report_dir.resolve()),
        "modelDir": str(args.model_dir.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
