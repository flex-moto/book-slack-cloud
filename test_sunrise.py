import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
from datetime import datetime
import monitor_sunrise as monitor
from monitor_sunrise import classify


class AvailabilityTests(unittest.TestCase):
    def test_filled_seats_notify_once_and_reopening_notifies(self):
        room = 'サンライズ出雲 / A寝台 禁煙個室'
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text(__import__('json').dumps({room: '空席残りわずか'}))
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan', side_effect=[{}, {}, {room: '空席あり'}]), patch.dict('os.environ', {'SUNRISE_NOTIFY': '1', 'SUNRISE_STATUS_UPDATE': '0'}), patch.object(monitor, 'send_alert') as send:
                clock.now.return_value = datetime(2026, 9, 18, 10, 0, tzinfo=monitor.JST)
                monitor.main()
                self.assertEqual(send.call_args.args[0], {})
                self.assertEqual(send.call_args.kwargs['closed'], {room: '空席残りわずか'})
                self.assertEqual(state.read_text(), '{}\n')
                monitor.main()
                self.assertEqual(send.call_count, 1)
                monitor.main()
                self.assertEqual(send.call_count, 2)
                self.assertEqual(send.call_args.args[0], {room: '空席あり'})

    def test_filled_notification_failure_preserves_previous_state(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text('{"room": "空席あり"}')
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan', return_value={}), patch.dict('os.environ', {'SUNRISE_NOTIFY': '1'}), patch.object(monitor, 'send_alert', side_effect=RuntimeError('Slack failed')):
                clock.now.return_value = datetime(2026, 9, 18, 10, 0, tzinfo=monitor.JST)
                with self.assertRaises(RuntimeError):
                    monitor.main()
                self.assertEqual(state.read_text(), '{"room": "空席あり"}')

    def test_mixed_changes_use_new_channel_and_clear_labels(self):
        with patch.dict('os.environ', {'SLACK_BOT_TOKEN': 'test', 'SLACK_CHANNEL_PB': 'old', 'SLACK_CHANNEL_SUNRISE': ''}), patch.object(monitor.requests, 'post') as post:
            post.return_value.json.return_value = {'ok': True, 'channel': monitor.DEFAULT_CHANNEL}
            monitor.send_alert({'サンライズ瀬戸 / B寝台 禁煙個室': '空席あり'}, closed={'サンライズ出雲 / A寝台 禁煙個室': '空席あり'})
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['channel'], 'C0C2LSTJD1T')
            self.assertIn('空席が出ました', payload['text'])
            self.assertIn('埋まりました', payload['text'])
            self.assertIn('サンライズ出雲 / A寝台 禁煙個室：空席なし', payload['text'])

    def test_channel_confirmation_can_report_no_availability(self):
        with patch.dict('os.environ', {'SLACK_BOT_TOKEN': 'test'}), patch.object(monitor.requests, 'post') as post:
            post.return_value.json.return_value = {'ok': True}
            monitor.send_alert({}, status_update=True)
            self.assertIn('現在、監視対象の空席はありません', post.call_args.kwargs['json']['text'])

    def test_empty_table_is_not_sold_out(self):
        with self.assertRaises(RuntimeError):
            classify([[], []])

    def test_known_service_pages(self):
        for text, error in [('ただいま受付時間外です。【20100941】', monitor.BookingServiceClosed),
                            ('混雑中です。【20100946】', monitor.BookingServiceBusy)]:
            with self.subTest(text=text), self.assertRaises(error):
                monitor.check_service_message(text)
        monitor.check_service_message('新規予約 経路・設備選択')

    def test_busy_retries_then_recovers(self):
        with patch.object(monitor, 'scan_once', side_effect=[monitor.BookingServiceBusy(), monitor.BrowserTimeout('timeout'), {}]) as scan, patch.object(monitor.time, 'sleep') as sleep:
            self.assertEqual(monitor.scan(), {})
            self.assertEqual(scan.call_count, 3)
            self.assertEqual([c.args[0] for c in sleep.call_args_list], [30, 60])

    def test_persistent_busy_still_fails(self):
        with patch.object(monitor, 'scan_once', side_effect=monitor.BookingServiceBusy()), patch.object(monitor.time, 'sleep'), self.assertRaises(monitor.BookingServiceBusy):
            monitor.scan()

    def test_unknown_layout_is_not_hidden_or_retried(self):
        with patch.object(monitor, 'scan_once', side_effect=RuntimeError('layout')) as scan, patch.object(monitor.time, 'sleep') as sleep, self.assertRaises(RuntimeError):
            monitor.scan()
        self.assertEqual(scan.call_count, 1)
        sleep.assert_not_called()

    def test_maintenance_preserves_state_and_never_notifies(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            state.write_text('{"room": "空席あり"}')
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'datetime') as clock, patch.object(monitor, 'scan_once', side_effect=monitor.BookingServiceClosed()) as scan, patch.object(monitor.time, 'sleep') as sleep, patch.object(monitor, 'send_alert') as send:
                clock.now.return_value = datetime(2026, 9, 18, 1, 30, tzinfo=monitor.JST)
                monitor.main()
                self.assertEqual(state.read_text(), '{"room": "空席あり"}')
                self.assertEqual(scan.call_count, 1)
                sleep.assert_not_called()
                send.assert_not_called()

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
