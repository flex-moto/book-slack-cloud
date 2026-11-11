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
        with patch.object(monitor, "date") as fake_date, patch.object(monitor, "WINDOW_DAYS", 0):
            fake_date.today.return_value = date(2026, 11, 12)
            self.assertEqual(monitor.scan_availability(), {"2026-11-12 19:00"})
        body = session.return_value.post.call_args.kwargs["json"]
        self.assertEqual(body["service_category_ids"], [monitor.COURT_CATEGORY_ID])
        self.assertEqual(body["orders"], [])

if __name__ == "__main__":
    unittest.main()
