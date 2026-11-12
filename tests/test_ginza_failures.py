import os
import unittest
from unittest.mock import patch
import monitor
import monitor_ginza_monthly as monthly


class GinzaFailureTests(unittest.TestCase):
    @patch.object(monitor, 'save_state')
    @patch.object(monitor, 'notify_slack')
    @patch.object(monitor, 'scan_availability', side_effect=RuntimeError('fetch failed'))
    def test_fetch_failure_is_visible_and_preserves_state(self, scan, notify, save):
        with self.assertRaises(SystemExit) as result:
            monitor.main()
        self.assertEqual(result.exception.code, 1)
        notify.assert_not_called()
        save.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_slack_token_raises_for_both_paths(self):
        from datetime import date
        with self.assertRaises(RuntimeError):
            monitor.notify_slack({'2026-11-12 19:00'}, set())
        with self.assertRaises(RuntimeError):
            monthly.notify(set(), date(2026, 12, 1))
