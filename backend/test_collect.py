import tempfile
import unittest
from unittest.mock import patch, MagicMock
import gzip
import json
from urllib.error import URLError
from pathlib import Path
from backend.collect import collect, connect, page_rows, normalize, CollectionError, fetch_page, collector_lock


def station(sid):
    return dict(stationId=sid, stationName="테스트", rackTotCnt="20",
                parkingBikeTotCnt="25", shared="125", stationLatitude="37.5",
                stationLongitude="127")


def response(rows):
    return {"rentBikeStatus": {"list_total_count": len(rows), "RESULT": {"CODE": "INFO-000"}, "row": rows}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        self.db = connect(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_pages_and_slot_idempotency(self):
        calls = []
        def fetch(key, start, end, archive):
            calls.append(start)
            return response([station("a"), station("b")] if start == 1 else [station("c")])
        result = collect(self.db, self.path, "secret", fetch, 600, 2)
        self.assertEqual(result["rows"], 3)
        self.assertEqual(calls, [1, 3])
        self.assertEqual(collect(self.db, self.path, "secret", fetch, 601, 2)["status"], "skipped")
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM latest_inventory").fetchone()[0], 3)

    def test_partial_does_not_replace_latest_and_retry_recovers(self):
        collect(self.db, self.path, "secret", lambda *a: response([station("old")]), 300, 2)
        def fail(key, start, end, archive):
            if start == 1:
                return response([station("a"), station("b")])
            raise CollectionError("network_error")
        self.assertEqual(collect(self.db, self.path, "secret", fail, 600, 2)["status"], "partial")
        self.assertEqual(self.db.execute("SELECT station_id FROM latest_inventory").fetchone()[0], "old")
        self.assertEqual(collect(self.db, self.path, "secret", lambda *a: response([station("new")]), 600, 2)["status"], "success")
        self.assertEqual(self.db.execute("SELECT station_id FROM latest_inventory").fetchone()[0], "new")

    def test_duplicate_and_empty_are_not_success(self):
        self.assertEqual(collect(self.db, self.path, "secret", lambda *a: response([station("a"), station("a")]), 600, 2)["status"], "failed")
        self.assertEqual(collect(self.db, self.path, "secret", lambda *a: response([]), 600, 2)["status"], "failed")

    def test_errors_and_invalid_numbers(self):
        with self.assertRaises(CollectionError):
            page_rows({"RESULT": {"CODE": "ERROR-300", "MESSAGE": "secret"}})
        self.assertEqual(page_rows({"RESULT": {"CODE": "INFO-200"}}), [])
        row = station("a")
        row["parkingBikeTotCnt"] = "NaN"
        with self.assertRaises(CollectionError):
            normalize(row)
        self.assertEqual(normalize(station("a"))[3], 25)

    def test_transport_retry_and_secret_redaction(self):
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = json.dumps(
            {"RESULT": {"CODE": "ERROR-300", "MESSAGE": "secret"}}).encode()
        with patch("backend.collect.urlopen", side_effect=[URLError("secret"), reply]) as request:
            with patch("backend.collect.time.sleep"):
                fetch_page("secret", 1, 1000, self.path)
        self.assertEqual(request.call_count, 2)
        with gzip.open(self.path / "1-1000-attempt2.json.gz", "rt") as source:
            self.assertNotIn("secret", source.read())

    def test_lock_release(self):
        with collector_lock(self.path):
            with self.assertRaises(CollectionError):
                with collector_lock(self.path):
                    pass
        with collector_lock(self.path):
            pass


if __name__ == "__main__":
    unittest.main()
