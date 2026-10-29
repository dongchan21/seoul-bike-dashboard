import unittest

from backend.download_station_master import district_from_address, parse_data_view


class StationMasterTests(unittest.TestCase):
    def test_parse_javascript_object_response(self):
        payload = (
            '{result:"ok",page:{pageNo:1,pageCount:1,totalCount:1,listCount:1},'
            'list:[{LOT:"127.03",RONUM:"1",ADDR2:"강남역",'
            'ADDR1:"서울특별시 강남구 테헤란로 1",RNTLS_ID:"ST-1",LAT:"37.49"},]}'
        )
        parsed = parse_data_view(payload)
        self.assertEqual("ST-1", parsed["list"][0]["RNTLS_ID"])

    def test_extract_district(self):
        self.assertEqual("강남구", district_from_address("서울특별시 강남구 테헤란로 1"))
        self.assertIsNone(district_from_address("경기도 성남시 분당구"))


if __name__ == "__main__":
    unittest.main()
