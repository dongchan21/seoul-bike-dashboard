import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

from backend.evaluate_baseline import Metrics, default_splits, evaluate


class BaselineEvaluationTest(unittest.TestCase):
    def test_metric_formulas(self):
        metrics = Metrics()
        metrics.add(2, 1)
        metrics.add(4, 6)
        result = metrics.as_dict()
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["mae"], 1.5)
        self.assertAlmostEqual(result["rmse"], (2.5) ** 0.5, places=6)
        self.assertEqual(result["wape"], 0.5)

    def test_default_split_has_no_overlap(self):
        result = default_splits("2025-10-09", "2026-10-08")
        self.assertEqual(result["trainEnd"], "2026-06-08")
        self.assertEqual(result["validationStart"], "2026-06-09")
        self.assertEqual(result["validationEnd"], "2026-08-08")
        self.assertEqual(result["testStart"], "2026-08-09")

    def test_backtest_uses_training_pattern_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "flows.sqlite3"
            with closing(sqlite3.connect(database)) as db:
                db.executescript(
                    """
                    CREATE TABLE flow_imports(
                      min_date TEXT, max_date TEXT, station_days INTEGER
                    );
                    CREATE TABLE flows_5m(
                      station_id TEXT, service_date TEXT, minute_of_day INTEGER,
                      rentals INTEGER, returns INTEGER,
                      PRIMARY KEY(station_id, service_date, minute_of_day)
                    );
                    """
                )
                start = date(2026, 1, 1)
                end = start + timedelta(days=20)
                db.execute("INSERT INTO flow_imports VALUES(?,?,?)", (str(start), str(end), 21))
                rows = []
                for offset in range(21):
                    day = start + timedelta(days=offset)
                    weekday = day.weekday()
                    for minute in range(0, 1440, 5):
                        rentals = 1 if weekday < 5 and 420 <= minute < 600 else 0
                        returns = 1 if weekday < 5 and 1020 <= minute < 1260 else 0
                        rows.append(("ST-1", str(day), minute, rentals, returns))
                db.executemany("INSERT INTO flows_5m VALUES(?,?,?,?,?)", rows)
                db.commit()

            periods = {
                "trainStart": "2026-01-01",
                "trainEnd": "2026-01-14",
                "validationStart": "2026-01-15",
                "validationEnd": "2026-01-17",
                "testStart": "2026-01-18",
                "testEnd": "2026-01-21",
            }
            output = root / "reports"
            result = evaluate(database, output, periods)
            seasonal_rows = [
                row for row in result["metrics"]["overall"]
                if row["split"] == "test"
                and row["model"] == "seasonal-mean"
                and row["target"] == "rentals30m"
            ]
            self.assertEqual(seasonal_rows[0]["mae"], 0.0)
            self.assertGreater(result["periodStats"]["test"]["windows"], 0)
            self.assertTrue((output / "evaluation.json").is_file())
            self.assertTrue((output / "overall.csv").is_file())
            self.assertTrue((output / "by_time_bucket.csv").is_file())
            self.assertTrue((output / "by_station.csv").is_file())


if __name__ == "__main__":
    unittest.main()
