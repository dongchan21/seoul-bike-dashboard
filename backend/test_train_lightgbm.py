from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest

from backend.train_lightgbm import FEATURE_NAMES, build_datasets


class LightGbmDatasetTest(unittest.TestCase):
    def test_builds_time_ordered_calendar_features_and_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flows.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(
                    """
                    CREATE TABLE flow_imports(min_date TEXT, max_date TEXT, station_days INTEGER);
                    CREATE TABLE station_master(
                      station_id TEXT PRIMARY KEY, district TEXT
                    );
                    CREATE TABLE flows_5m(
                      station_id TEXT, service_date TEXT, minute_of_day INTEGER,
                      rentals INTEGER, returns INTEGER,
                      PRIMARY KEY(station_id, service_date, minute_of_day)
                    );
                    """
                )
                start = date(2026, 1, 1)
                end = start + timedelta(days=11)
                db.execute("INSERT INTO flow_imports VALUES(?,?,?)", (str(start), str(end), 12))
                db.execute("INSERT INTO station_master VALUES('ST-1','강남구')")
                rows = []
                for offset in range(12):
                    day = start + timedelta(days=offset)
                    for minute in range(0, 1440, 5):
                        rows.append(("ST-1", str(day), minute, 1, 2))
                db.executemany("INSERT INTO flows_5m VALUES(?,?,?,?,?)", rows)
                db.commit()
            periods = {
                "trainStart": "2026-01-01", "trainEnd": "2026-01-08",
                "validationStart": "2026-01-09", "validationEnd": "2026-01-10",
                "testStart": "2026-01-11", "testEnd": "2026-01-12",
            }
            datasets, returned, mapping, counts = build_datasets(path, periods)
            self.assertEqual(returned, periods)
            self.assertEqual(mapping, {"ST-1": 0})
            self.assertEqual(counts["train"], 8 * 47)
            self.assertEqual(datasets["test"]["X"].shape, (2 * 47, len(FEATURE_NAMES)))
            self.assertTrue((datasets["train"]["rentals"] == 6).all())
            self.assertTrue((datasets["train"]["returns"] == 12).all())
            self.assertEqual(int(datasets["train"]["X"][0, 2]), 1)


if __name__ == "__main__":
    unittest.main()
