from pathlib import Path
import tempfile
import unittest
import zipfile

from backend.download_history import (
    HistoryDownloadError,
    HistoryFile,
    parse_catalog,
    parse_disposition_filename,
    select_entries,
    validate_file,
)


class HistoryDownloadTests(unittest.TestCase):
    def setUp(self):
        self.catalog_html = """
        <table><tbody>
          <tr>
            <td>1</td><td>서울특별시 공공자전거 대여이력 정보_2606.csv</td>
            <td>716333.37</td><td>2026.07.15</td><td>2026.07.15</td>
            <td><a href="javascript:downloadFile('150')">DOWN</a></td>
          </tr>
          <tr>
            <td>2</td><td>서울특별시 공공자전거 대여이력 정보_2025.zip</td>
            <td>1736953.98</td><td>2026.04.22</td><td>2026.04.22</td>
            <td><a href="javascript:downloadFile('96')">DOWN</a></td>
          </tr>
          <tr>
            <td>3</td><td>tpss_bcycl_od_statnhm_20261007.zip</td>
            <td>5582.8</td><td>2026.10.12</td><td>2026.10.12</td>
            <td><a href="javascript:downloadFile('261007')">DOWN</a></td>
          </tr>
        </tbody></table>
        """

    def test_parse_catalog_and_periods(self):
        entries = parse_catalog(self.catalog_html)
        self.assertEqual(3, len(entries))
        self.assertEqual("150", entries[0].seq)
        self.assertEqual("2026-06", entries[0].period)
        self.assertEqual("2025", entries[1].period)
        self.assertGreater(entries[0].expected_bytes, 700_000_000)
        self.assertEqual("2026-10-07", entries[2].period)

    def test_select_by_year_month_and_latest(self):
        entries = parse_catalog(self.catalog_html)
        self.assertEqual([entries[0]], select_entries(entries, periods=["2026-06"]))
        self.assertEqual([entries[1]], select_entries(entries, periods=["2025"]))
        self.assertEqual([entries[2]], select_entries(entries, latest=True))
        self.assertEqual([entries[2]], select_entries(entries, periods=["2026-10-07"]))

    def test_invalid_period_fails(self):
        entries = parse_catalog(self.catalog_html)
        with self.assertRaises(HistoryDownloadError):
            select_entries(entries, periods=["2026-13"])

    def test_content_disposition_percent_encoded_filename(self):
        header = (
            'attachment; filename="%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C'
            '%20%EA%B3%B5%EA%B3%B5%EC%9E%90%EC%A0%84%EA%B1%B0_2015.zip"'
        )
        self.assertEqual(
            "서울특별시 공공자전거_2015.zip",
            parse_disposition_filename(header),
        )

    def test_content_disposition_utf8_bytes_exposed_as_latin1(self):
        filename = "서울특별시 공공자전거 대여이력 정보_2015.zip"
        mojibake = filename.encode("utf-8").decode("latin-1")
        self.assertEqual(
            filename,
            parse_disposition_filename(f'attachment; filename="{mojibake}"'),
        )

    def test_validate_zip_and_reject_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "history_2025.zip"
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("sample.csv", "대여소,건수\n101,1\n")
            entry = HistoryFile(
                seq="1",
                filename=archive.name,
                size_kib=archive.stat().st_size / 1024,
                published_at="2026.01.01",
                updated_at="2026.01.01",
            )
            validate_file(archive, entry)

            error_page = root / "error.csv"
            error_page.write_text("<html>error</html>", encoding="utf-8")
            error_entry = HistoryFile(
                seq="2",
                filename=error_page.name,
                size_kib=error_page.stat().st_size / 1024,
                published_at="2026.01.01",
                updated_at="2026.01.01",
            )
            with self.assertRaises(HistoryDownloadError):
                validate_file(error_page, error_entry)


if __name__ == "__main__":
    unittest.main()
