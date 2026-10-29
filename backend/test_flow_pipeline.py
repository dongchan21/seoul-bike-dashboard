import csv
from contextlib import closing
from datetime import datetime
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from backend.aggregate_flows import FlowImportError, connect, import_flow_zip
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


def write_monthly_zip(path: Path) -> None:
    first = io.StringIO(newline="")
    writer = csv.writer(first)
    writer.writerow(HEADERS)
    writer.writerow(["20261008", "출발시간", "0800", "ST-1", "출발", "ST-2", "도착", 3, 5, 1000])
    second = first.getvalue().replace("20261008", "20261009")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("flow_20261009.csv", second.encode("cp949"))
        archive.writestr("flow_20261008.csv", first.getvalue().encode("cp949"))


class FlowPipelineTests(unittest.TestCase):
    def test_monthly_zip_with_multiple_unsorted_csv_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "tpss_bcycl_od_statnhm_202610.zip"
            write_monthly_zip(archive)
            with closing(connect(root / "test.sqlite3")) as db:
                result = import_flow_zip(archive, db)
                self.assertEqual(2, result["sourceRows"])
                self.assertEqual(576, result["denseRows"])
                self.assertEqual(
                    ("2026-10-08", "2026-10-09"),
                    db.execute("SELECT min(service_date), max(service_date) FROM flows_5m").fetchone(),
                )

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

    def test_district_filter_is_applied_before_dense_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "tpss_bcycl_od_statnhm_20261008.zip"
            database = root / "gangnam.sqlite3"
            write_zip(archive)
            with closing(connect(database)) as db:
                db.execute(
                    """INSERT INTO station_master(
                         station_id, station_name, source, updated_at, district
                       ) VALUES('ST-1','강남 대여소','test','2026-10-13','강남구')"""
                )
                db.commit()
                result = import_flow_zip(
                    archive,
                    db,
                    district="강남구",
                    start_date="2026-10-08",
                    end_date="2026-10-08",
                )
                self.assertEqual(288, result["denseRows"])
                self.assertEqual(1, result["acceptedRows"])
                self.assertEqual(288, db.execute("SELECT count(*) FROM flows_5m").fetchone()[0])
                self.assertEqual(
                    (3, 0),
                    db.execute(
                        "SELECT rentals, returns FROM flows_5m "
                        "WHERE station_id='ST-1' AND minute_of_day=480"
                    ).fetchone(),
                )
                with self.assertRaises(FlowImportError):
                    import_flow_zip(
                        archive,
                        db,
                        force=True,
                        district="강남구",
                        start_date="2026-10-09",
                    )


if __name__ == "__main__":
    unittest.main()
