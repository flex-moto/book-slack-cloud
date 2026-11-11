import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor_reserve_one as monitor

class ReserveOneTest(unittest.TestCase):
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

    def test_stops_at_21_jst(self):
        fake_datetime = MagicMock(wraps=datetime)
        fake_datetime.now.return_value = datetime(2026, 12, 19, 21, tzinfo=monitor.JST)
        fake_datetime.combine.side_effect = datetime.combine
        with patch.object(monitor, 'datetime', fake_datetime), patch.object(monitor, 'sync_playwright') as browser, patch.object(sys, 'argv', ['monitor']):
            monitor.main()
        browser.assert_not_called()

if __name__ == '__main__': unittest.main()
