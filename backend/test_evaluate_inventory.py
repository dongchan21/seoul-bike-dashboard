from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.evaluate_inventory import Confusion, evaluate


class InventoryEvaluationTest(unittest.TestCase):
    def test_status_metrics(self):
        values = Confusion()
        values.add("shortage", "shortage")
        values.add("shortage", "normal")
        values.add("normal", "normal")
        result = values.as_dict()
        self.assertEqual(result["samples"], 3)
        self.assertAlmostEqual(result["perStatus"]["shortage"]["recall"], 0.5)

    def test_paired_inventory_evaluation_excludes_training_period(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "inventory.sqlite3"
            prediction = root / "prediction.sqlite3"
            with closing(sqlite3.connect(prediction)) as db:
                db.executescript(
                    """
                    CREATE TABLE baseline_models(
                      model_version TEXT PRIMARY KEY, trained_at TEXT,
                      training_start TEXT, training_end TEXT, training_rows INTEGER,
                      station_count INTEGER, notes TEXT
                    );
                    CREATE TABLE baseline_5m(
                      model_version TEXT, station_id TEXT, weekday INTEGER,
                      minute_of_day INTEGER, sample_count INTEGER,
                      expected_rentals REAL, expected_returns REAL
                    );
                    """
                )
                db.execute(
                    "INSERT INTO baseline_models VALUES(?,?,?,?,?,?,?)",
                    ("seasonal-mean-v1", "now", "2025-01-01", "2026-01-01", 1, 1, "test"),
                )
                origin = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
                kst = origin.astimezone(timezone(timedelta(hours=9)))
                for offset in range(0, 30, 5):
                    target = kst + timedelta(minutes=offset)
                    db.execute(
                        "INSERT INTO baseline_5m VALUES(?,?,?,?,?,?,?)",
                        (
                            "seasonal-mean-v1", "ST-1", target.weekday(),
                            target.hour * 60 + target.minute, 10, 0.0, 1.0,
                        ),
                    )
                db.commit()

            with closing(sqlite3.connect(inventory)) as db:
                db.executescript(
                    """
                    CREATE TABLE slots(slot TEXT PRIMARY KEY, run_id TEXT);
                    CREATE TABLE observations(
                      run_id TEXT, station_id TEXT, rack_count INTEGER,
                      current_bikes INTEGER
                    );
                    """
                )
                origin = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
                target = origin + timedelta(minutes=30)
                db.executemany(
                    "INSERT INTO slots VALUES(?,?)",
                    [(origin.isoformat(), "r1"), (target.isoformat(), "r2")],
                )
                db.executemany(
                    "INSERT INTO observations VALUES(?,?,?,?)",
                    [("r1", "ST-1", 20, 4), ("r2", "ST-1", 20, 9)],
                )
                db.commit()

            output = root / "reports"
            result = evaluate(inventory, prediction, output)
            self.assertEqual(result["counts"]["eligible30MinuteSlotPairs"], 1)
            self.assertEqual(result["counts"]["stationForecasts"], 1)
            self.assertEqual(result["inventoryMetrics"]["seasonal-mean"]["mae"], 1.0)
            self.assertEqual(result["inventoryMetrics"]["zero-change"]["mae"], 5.0)
            self.assertTrue((output / "evaluation.json").is_file())


if __name__ == "__main__":
    unittest.main()
