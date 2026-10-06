import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
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

    def tearDown(self):
        self.temp.cleanup()

    def test_latest_inventory_shape(self):
        row = latest_stations(self.path)[0]
        self.assertEqual(row["stationId"], "ST-1")
        self.assertEqual(row["currentBikes"], 7)

    def test_status_and_history(self):
        self.assertEqual(inventory_status(self.path)["stationCount"], 1)
        self.assertEqual(station_history("ST-1", 13, self.path)[0]["currentBikes"], 7)


if __name__ == "__main__":
    unittest.main()
