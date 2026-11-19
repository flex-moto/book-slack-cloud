import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor_reserve_one as monitor

class ReserveOneTest(unittest.TestCase):
    def test_availability_response_formats_and_invalid_data(self):
        monitor.validate_availability_response('0:{}\n1:[]\n')
        monitor.validate_availability_response('0:{}\n1:{"reservations":[],"closures":[],"specialOpenings":[]}\n')
        for body in ('0:{}', '1:{}', '1:{"reservations":[],"closures":[],"specialOpenings":null}'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                monitor.validate_availability_response(body)

    def test_expired_slots_are_not_reported(self):
        now = datetime(2026, 12, 19, 8, 0, tzinfo=monitor.JST)
        data = {'07:00 コートA': 'available', '08:00 コートA': 'available', '09:00 コートA': 'available'}
        self.assertEqual(monitor.eligible_slots(data, now), {'09:00 コートA': 'available'})

    def test_failed_fetch_preserves_state_and_returns_failure(self):
        with TemporaryDirectory() as folder:
            state = Path(folder) / 'state.json'
            state.write_text('{"asics": {"09:00 Aコート": "available"}}')
            before = state.read_text()
            browser = MagicMock()
            pw = MagicMock()
            pw.chromium.launch.return_value = browser
            context = MagicMock()
            context.__enter__.return_value = pw
            fake_datetime = MagicMock(wraps=datetime)
            fake_datetime.now.return_value = datetime(2026, 12, 19, 8, tzinfo=monitor.JST)
            fake_datetime.combine.side_effect = datetime.combine
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime', fake_datetime), \
                 patch.object(monitor, 'sync_playwright', return_value=context), \
                 patch.object(monitor, 'read_grid', side_effect=RuntimeError('fetch failed')), \
                 patch.object(monitor, 'slack') as slack, patch.object(sys, 'argv', ['monitor', '--facility', 'asics']):
                with self.assertRaises(SystemExit) as ex:
                    monitor.main()
            self.assertEqual(ex.exception.code, 1)
            self.assertEqual(state.read_text(), before)
            slack.assert_not_called()

    def test_availability_body_is_read_from_route_before_browser_response(self):
        page = MagicMock()
        page.get_by_role.return_value.count.side_effect = [0, 1]
        page.url = 'https://example.test/calendar'
        route = MagicMock()
        route.request.method = 'POST'
        route.request.url = page.url
        route.request.post_data = '{"from":"2026-12-19"}'
        upstream = route.fetch.return_value
        upstream.text.return_value = '0:{}\n1:[]\n'
        browser_response = page.expect_response.return_value.__enter__.return_value.value
        browser_response.status = 200
        browser_response.text.side_effect = monitor.PlaywrightError('Body discarded')

        def click():
            if page.route.called:
                page.route.call_args.args[1](route)

        page.get_by_role.return_value.click.side_effect = click
        with patch.object(monitor, 'validate_availability_response', side_effect=ValueError('checked')) as validate:
            with self.assertRaisesRegex(ValueError, 'checked'):
                monitor.read_grid(page, ['Aコート'])
        validate.assert_called_once_with(upstream.text.return_value)
        route.fulfill.assert_called_once_with(response=upstream)
        upstream.dispose.assert_called_once()
        browser_response.text.assert_not_called()
        page.unroute.assert_called_once_with(*page.route.call_args.args)

    def test_stops_at_21_jst(self):
        fake_datetime = MagicMock(wraps=datetime)
        fake_datetime.now.return_value = datetime(2026, 12, 19, 21, tzinfo=monitor.JST)
        fake_datetime.combine.side_effect = datetime.combine
        with patch.object(monitor, 'datetime', fake_datetime), patch.object(monitor, 'sync_playwright') as browser, patch.object(sys, 'argv', ['monitor']):
            monitor.main()
        browser.assert_not_called()

if __name__ == '__main__': unittest.main()
