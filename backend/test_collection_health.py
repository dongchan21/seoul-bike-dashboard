from datetime import datetime, timedelta, timezone
import unittest

from backend.collection_health import analyze_slots


KST = timezone(timedelta(hours=9))


class CollectionHealthTest(unittest.TestCase):
    def test_complete_recent_slots_are_normal(self):
        now = datetime(2026, 11, 5, 0, 20, tzinfo=KST)
        start = datetime(2026, 11, 5, 0, 0, tzinfo=KST)
        slots = [(start + timedelta(minutes=5 * index)).isoformat() for index in range(5)]
        result = analyze_slots(slots, now=now, days=1)
        self.assertEqual(result["status"], "normal")
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["missingSlots"], 0)

    def test_missing_and_delayed_slots_are_reported(self):
        now = datetime(2026, 11, 5, 0, 30, tzinfo=KST)
        slots = [
            datetime(2026, 11, 5, 0, 0, tzinfo=KST).isoformat(),
            datetime(2026, 11, 5, 0, 5, tzinfo=KST).isoformat(),
        ]
        result = analyze_slots(slots, now=now, days=1)
        self.assertEqual(result["status"], "delayed")
        self.assertEqual(result["lastSuccessAgeMinutes"], 25.0)
        self.assertEqual(result["missingSlots"], 5)
        self.assertEqual(result["longestMissingSlots"], 5)

    def test_incomplete_but_recent_collection(self):
        now = datetime(2026, 11, 5, 0, 20, tzinfo=KST)
        slots = [
            datetime(2026, 11, 5, 0, 0, tzinfo=KST).isoformat(),
            datetime(2026, 11, 5, 0, 15, tzinfo=KST).isoformat(),
            datetime(2026, 11, 5, 0, 20, tzinfo=KST).isoformat(),
        ]
        result = analyze_slots(slots, now=now, days=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missingSlots"], 2)


if __name__ == "__main__":
    unittest.main()
