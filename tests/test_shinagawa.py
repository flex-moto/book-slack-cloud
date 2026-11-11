import os
import unittest
from unittest.mock import patch
import monitor_shinagawa as monitor


class ShinagawaFailureTests(unittest.TestCase):
    @patch.dict(os.environ, {"SHINAGAWA_FORCE": "1"})
    @patch.object(monitor, "save_state")
    @patch.object(monitor, "notify_slack")
    @patch.object(monitor, "scan_availability", side_effect=RuntimeError("empty"))
    def test_scan_failure_fails_without_notification_or_state(self, scan, notify, save):
        with self.assertRaises(SystemExit) as result:
            monitor.main()
        self.assertEqual(result.exception.code, 1)
        notify.assert_not_called()
        save.assert_not_called()

    @patch.dict(os.environ, {"SHINAGAWA_FORCE": "1"}, clear=True)
    @patch.object(monitor, "save_state")
    @patch.object(monitor, "load_previous", return_value=set())
    @patch.object(monitor, "scan_availability", return_value={"2026-11-12 19:00"})
    def test_missing_slack_token_does_not_advance_state(self, scan, load, save):
        with self.assertRaises(RuntimeError):
            monitor.main()
        save.assert_not_called()


    @patch.object(monitor.time, "sleep")
    @patch.object(monitor.requests, "Session")
    def test_category_and_exact_time_are_required(self, session, sleep):
        from datetime import date
        response = session.return_value.post.return_value
        response.json.return_value = {"availability_grid": {"data": [
            {"t": "2026-11-12T10:00:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
            {"t": "2026-11-12T11:00:00Z", "a": True, "sc": "other"},
            {"t": "2026-11-12T11:30:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
        ]}}
        with patch.object(monitor, "datetime") as fake_datetime, patch.object(monitor, "WINDOW_DAYS", 0):
            fake_datetime.now.return_value.date.return_value = date(2026, 11, 12)
            self.assertEqual(monitor.scan_availability(), {"2026-11-12 19:00"})
        body = session.return_value.post.call_args.kwargs["json"]
        self.assertEqual(body["service_category_ids"], [monitor.COURT_CATEGORY_ID])
        self.assertEqual(body["orders"], [])

    @patch.object(monitor.time, "sleep")
    @patch.object(monitor.requests, "Session")
    def test_weekend_hours_and_18_excluded(self, session, sleep):
        from datetime import date
        session.return_value.post.return_value.json.return_value = {"availability_grid": {"data": [
            {"t": "2026-11-14T03:00:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
            {"t": "2026-11-14T08:00:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
            {"t": "2026-11-14T09:00:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
        ]}}
        with patch.object(monitor, "datetime") as clock, patch.object(monitor, "WINDOW_DAYS", 0):
            clock.now.return_value.date.return_value = date(2026, 11, 14)
            self.assertEqual(monitor.scan_availability(), {"2026-11-14 12:00", "2026-11-14 17:00"})
        self.assertEqual(session.return_value.post.call_count, 6)

    @patch.object(monitor.time, "sleep")
    @patch.object(monitor.requests, "Session")
    def test_public_holiday_uses_weekend_hours(self, session, sleep):
        from datetime import date
        session.return_value.post.return_value.json.return_value = {"availability_grid": {"data": [
            {"t": "2026-11-23T03:00:00Z", "a": True, "sc": monitor.COURT_CATEGORY_ID},
        ]}}
        with patch.object(monitor, "datetime") as clock, patch.object(monitor, "WINDOW_DAYS", 0):
            clock.now.return_value.date.return_value = date(2026, 11, 23)  # 勤労感謝の日(月)
            self.assertEqual(monitor.scan_availability(), {"2026-11-23 12:00"})
        self.assertEqual(session.return_value.post.call_count, 6)


class OpeningWindowTests(unittest.TestCase):
    def at(self, *args):
        from datetime import datetime
        return datetime(*args, tzinfo=monitor.JST)

    def test_weekend_opening_two_weeks_before_bypasses_gate(self):
        # 2026-12-19(土) 12:00〜17:00 の枠は 12/5 の同時刻に開放される
        self.assertTrue(monitor.in_opening_window(self.at(2026, 12, 5, 11, 45)))
        self.assertTrue(monitor.in_opening_window(self.at(2026, 12, 5, 14, 15)))
        self.assertTrue(monitor.in_opening_window(self.at(2026, 12, 5, 17, 20)))
        self.assertFalse(monitor.in_opening_window(self.at(2026, 12, 5, 17, 30)))
        self.assertFalse(monitor.in_opening_window(self.at(2026, 12, 5, 11, 30)))

    def test_weekday_opening_uses_evening_hours(self):
        # 2026-12-21(月) 19:00 / 20:00 の枠は 12/7 の同時刻に開放される
        self.assertTrue(monitor.in_opening_window(self.at(2026, 12, 7, 19, 10)))
        self.assertFalse(monitor.in_opening_window(self.at(2026, 12, 7, 12, 0)))

    def test_holiday_opening_uses_weekend_hours(self):
        # 2027-01-11(月・成人の日) の枠は 2026-12-28 12:00〜 に開放される
        self.assertTrue(monitor.in_opening_window(self.at(2026, 12, 28, 13, 0)))

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(monitor, "scan_availability", side_effect=RuntimeError("ran"))
    def test_gate_skips_outside_opening_window(self, scan):
        from datetime import datetime
        with patch.object(monitor, "datetime") as clock:
            clock.side_effect = datetime
            clock.now.return_value = self.at(2026, 12, 2, 10, 20)
            monitor.main()
        scan.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(monitor, "scan_availability", side_effect=RuntimeError("ran"))
    def test_gate_bypassed_inside_opening_window(self, scan):
        from datetime import datetime
        with patch.object(monitor, "datetime") as clock:
            clock.side_effect = datetime
            clock.now.return_value = self.at(2026, 12, 5, 12, 20)
            with self.assertRaises(SystemExit):
                monitor.main()
        scan.assert_called_once()


if __name__ == "__main__":
    unittest.main()
