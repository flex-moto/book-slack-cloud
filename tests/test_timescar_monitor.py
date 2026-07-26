import os
import unittest
from unittest import mock

import timescar_monitor as monitor


class CookieParsingTests(unittest.TestCase):
    def test_parse_cookie_header_preserves_values_containing_equals(self):
        self.assertEqual(
            monitor._parse_cookie_str("session=abc==; flag=1", "https://example.test"),
            [
                {"name": "session", "value": "abc==", "url": "https://example.test"},
                {"name": "flag", "value": "1", "url": "https://example.test"},
            ],
        )

    def test_scan_requires_both_cookie_secrets(self):
        with mock.patch.dict(os.environ, {"TIMESCAR_COOKIE": "share=1"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TIMESCAR_COOKIE_TIMESCLUB"):
                monitor.scan_availability()


class FailureReportingTests(unittest.TestCase):
    def test_cookie_expired_message_mentions_both_secrets(self):
        with mock.patch.object(monitor, "_slack_post") as post:
            monitor.notify_cookie_expired()
        message = post.call_args.args[0]
        self.assertIn("TIMESCAR_COOKIE", message)
        self.assertIn("TIMESCAR_COOKIE_TIMESCLUB", message)

    def test_unexpected_failure_exits_nonzero(self):
        with mock.patch.object(
            monitor, "scan_availability", side_effect=RuntimeError("test failure")
        ):
            with self.assertRaises(SystemExit) as raised:
                monitor.main()
        self.assertEqual(raised.exception.code, 1)

    def test_login_failure_exits_nonzero(self):
        with mock.patch.object(
            monitor,
            "scan_availability",
            side_effect=monitor.LoginRequired("cookie_expired", "https://api.timesclub.jp/"),
        ), mock.patch.object(
            monitor, "_bump_and_should_notify", return_value=(False, 4)
        ):
            with self.assertRaises(SystemExit) as raised:
                monitor.main()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
