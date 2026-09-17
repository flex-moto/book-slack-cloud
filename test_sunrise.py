import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime
import monitor_sunrise as monitor
from monitor_sunrise import classify


class AvailabilityTests(unittest.TestCase):
    def test_real_test_payload_uses_test_date_and_label(self):
        target = datetime(2026, 10, 14, 22, 34, tzinfo=monitor.JST)
        with patch.dict('os.environ', {'SLACK_BOT_TOKEN': 'test'}), patch.object(monitor.requests, 'post') as post:
            post.return_value.json.return_value = {'ok': True}
            monitor.send_alert({'サンライズ瀬戸 / 普通車指定席 禁煙席': '空席あり'}, target, test=True)
            message = post.call_args.kwargs['json']['text']
            self.assertIn('【実地テスト】', message)
            self.assertIn('2026/10/14', message)
            self.assertIn('inputDate=20261014', message)
            self.assertNotIn('inputDate=20260924', message)
            self.assertEqual(monitor.DEPARTURE.day, 24)

    def test_sold_out(self):
        self.assertEqual(classify([['普通車指定席 禁煙席', 'B寝台 禁煙個室'], ['残席なし', '残席なし']]), {})

    def test_only_correct_category_is_available(self):
        self.assertEqual(classify([['普通車指定席 禁煙席', 'B寝台 禁煙個室'], ['残席なし', '空席残りわずか 2']]), {'B寝台 禁煙個室': '空席残りわずか 2'})

    def test_unknown_is_error_not_sold_out(self):
        with self.assertRaises(RuntimeError):
            classify([['A寝台 禁煙個室'], ['照会できません']])

    def test_changed_layout_is_error(self):
        with self.assertRaises(RuntimeError):
            classify([['A寝台 禁煙個室'], []])

    def test_slack_failure_preserves_state(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text('{}')
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan', return_value={'瀬戸 / B寝台 禁煙個室': '空席あり'}), patch.dict('os.environ', {'SUNRISE_NOTIFY': '1', 'SLACK_BOT_TOKEN': 'test'}), patch.object(monitor.requests, 'post') as post:
                clock.now.return_value = datetime(2026, 9, 17, 16, 0, tzinfo=monitor.JST)
                post.return_value.json.return_value = {'ok': False, 'error': 'not_in_channel'}
                with self.assertRaises(RuntimeError):
                    monitor.main()
                self.assertEqual(state.read_text(), '{}')

    def test_sold_out_never_sends_slack(self):
        with TemporaryDirectory() as directory:
            with patch.object(monitor, 'STATE', Path(directory) / 'state.json'), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan', return_value={}), patch.dict('os.environ', {'SUNRISE_NOTIFY': '1'}), patch.object(monitor.requests, 'post') as post:
                clock.now.return_value = datetime(2026, 9, 17, 16, 0, tzinfo=monitor.JST)
                monitor.main()
                post.assert_not_called()

    def test_unchanged_available_is_silent(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text('{"room": "空席あり"}')
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan', return_value={'room': '空席あり'}), patch.dict('os.environ', {'SUNRISE_NOTIFY': '1'}), patch.object(monitor.requests, 'post') as post:
                clock.now.return_value = datetime(2026, 9, 17, 16, 0, tzinfo=monitor.JST)
                monitor.main()
                post.assert_not_called()

    def test_departure_stops_network_access(self):
        with patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan') as scan:
            clock.now.return_value = monitor.DEPARTURE
            monitor.main()
            scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
