import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.api import inventory_status, latest_stations, station_history


class ApiQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        db = sqlite3.connect(self.path)
        db.executescript("""
          CREATE TABLE runs(id TEXT PRIMARY KEY, slot TEXT, started_at TEXT,
            finished_at TEXT, status TEXT, row_count INTEGER, error TEXT);
          CREATE TABLE observations(run_id TEXT, station_id TEXT, name TEXT,
            rack_count INTEGER, current_bikes INTEGER, shared REAL,
            latitude REAL, longitude REAL, fetched_at TEXT,
            source_observed_at TEXT, PRIMARY KEY(run_id, station_id));
          CREATE TABLE slots(slot TEXT PRIMARY KEY, run_id TEXT);
          CREATE VIEW latest_inventory AS
            SELECT o.*, r.slot FROM observations o JOIN runs r ON o.run_id=r.id
            WHERE o.run_id=(SELECT run_id FROM slots ORDER BY slot DESC LIMIT 1);
        """)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",
                   ("run-1", now, now, now, "success", 1, None))
        db.execute("INSERT INTO slots VALUES(?,?)", (now, "run-1"))
        db.execute("INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("run-1", "ST-1", "테스트", 10, 7, 70, 37.5, 127.0, now, None))
        db.commit()
        db.close()

        self.prediction_path = Path(self.temp.name) / "prediction.sqlite3"
        model = sqlite3.connect(self.prediction_path)
        model.executescript("""
          CREATE TABLE station_master(
            station_id TEXT PRIMARY KEY, district TEXT, address TEXT
          );
          CREATE TABLE baseline_models(
            model_version TEXT PRIMARY KEY, trained_at TEXT, training_start TEXT,
            training_end TEXT, training_rows INTEGER, station_count INTEGER, notes TEXT
          );
          CREATE TABLE baseline_5m(
            model_version TEXT, station_id TEXT, weekday INTEGER,
            minute_of_day INTEGER, sample_count INTEGER,
            expected_rentals REAL, expected_returns REAL,
            PRIMARY KEY(model_version, station_id, weekday, minute_of_day)
          );
        """)
        model.execute(
            "INSERT INTO station_master VALUES('ST-1','강남구','서울특별시 강남구 테스트로 1')"
        )
        model.execute(
            "INSERT INTO baseline_models VALUES(?,?,?,?,?,?,?)",
            ("seasonal-mean-v1", now, "2025-10-09", "2026-10-08", 1000, 1, "test"),
        )
        self.as_of = datetime.fromisoformat("2026-10-13T08:00:00+09:00")
        for offset in range(0, 30, 5):
            point = self.as_of + timedelta(minutes=offset)
            model.execute(
                "INSERT INTO baseline_5m VALUES(?,?,?,?,?,?,?)",
                (
                    "seasonal-mean-v1", "ST-1", point.weekday(),
                    point.hour * 60 + point.minute, 10, 2.0, 1.0,
                ),
            )
        model.commit()
        model.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_latest_inventory_shape(self):
        row = latest_stations(self.path)[0]
        self.assertEqual(row["stationId"], "ST-1")
        self.assertEqual(row["currentBikes"], 7)

    def test_status_and_history(self):
        self.assertEqual(inventory_status(self.path)["stationCount"], 1)
        self.assertEqual(station_history("ST-1", 13, self.path)[0]["currentBikes"], 7)

    def test_latest_inventory_with_30_minute_baseline_prediction(self):
        row = latest_stations(
            self.path,
            prediction_path=self.prediction_path,
            as_of=self.as_of,
        )[0]
        self.assertTrue(row["predictionAvailable"])
        self.assertEqual(row["district"], "강남구")
        self.assertEqual(row["expectedRentals30m"], 12.0)
        self.assertEqual(row["expectedReturns30m"], 6.0)
        self.assertEqual(row["expectedBikes30m"], 1.0)
        self.assertEqual(row["forecastStatus"], "shortage")
        self.assertEqual(row["recommendedAction"], "replenish")
        self.assertEqual(row["recommendedQuantity"], 4)
        self.assertEqual(row["priority"], 1)

    def test_status_includes_prediction_model_metadata(self):
        status = inventory_status(self.path, prediction_path=self.prediction_path)
        self.assertEqual(status["predictionModel"]["modelVersion"], "seasonal-mean-v1")
        self.assertEqual(status["predictionModel"]["horizonMinutes"], 30)


if __name__ == "__main__":
    unittest.main()
