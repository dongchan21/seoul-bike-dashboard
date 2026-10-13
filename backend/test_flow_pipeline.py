import csv
from contextlib import closing
from datetime import datetime
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from backend.aggregate_flows import connect, import_flow_zip
from backend.baseline import predict_30m, train_baseline


HEADERS = [
    "기준_날짜", "집계_기준", "기준_시간대", "시작_대여소_ID",
    "시작_대여소명", "종료_대여소_ID", "종료_대여소명", "전체_건수",
    "전체_이용_분", "전체_이용_거리",
]


def write_zip(path: Path) -> None:
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(HEADERS)
    writer.writerow(["20261008", "출발시간", "0800", "ST-1", "출발", "ST-2", "도착", 3, 5, 1000])
    writer.writerow(["20261008", "도착시간", "0805", "ST-1", "출발", "ST-2", "도착", 2, 5, 1000])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path.with_suffix(".csv").name, text.getvalue().encode("cp949"))


class FlowPipelineTests(unittest.TestCase):
    def test_import_dense_rows_idempotency_and_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "tpss_bcycl_od_statnhm_20261008.zip"
            database = root / "test.sqlite3"
            write_zip(archive)
            with closing(connect(database)) as db:
                result = import_flow_zip(archive, db)
                self.assertEqual("imported", result["status"])
                self.assertEqual(576, result["denseRows"])
                self.assertEqual((3, 0), db.execute(
                    "SELECT rentals, returns FROM flows_5m WHERE station_id='ST-1' AND minute_of_day=480"
                ).fetchone())
                self.assertEqual((0, 2), db.execute(
                    "SELECT rentals, returns FROM flows_5m WHERE station_id='ST-2' AND minute_of_day=485"
                ).fetchone())
                self.assertEqual((0, 0), db.execute(
                    "SELECT rentals, returns FROM flows_5m WHERE station_id='ST-1' AND minute_of_day=0"
                ).fetchone())
                self.assertEqual("skipped", import_flow_zip(archive, db)["status"])

                trained = train_baseline(db)
                self.assertEqual(576, trained["trainingRows"])
                prediction = predict_30m(db, "ST-1", datetime.fromisoformat("2026-10-08T08:00:00+09:00"))
                self.assertEqual(3.0, prediction["expectedRentals30m"])
                self.assertEqual(0.0, prediction["expectedReturns30m"])


if __name__ == "__main__":
    unittest.main()
