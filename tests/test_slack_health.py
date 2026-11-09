"""No live API calls; credential safety and authentication regressions."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from slack_health import check_slack_auth


class AuthTests(unittest.TestCase):
    def test_invalid_auth_reports_code_without_token(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / 'summary.md'
            output = io.StringIO()
            with patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': str(summary)}), patch('slack_health.urllib.request.urlopen') as request, contextlib.redirect_stdout(output):
                request.return_value.__enter__.return_value.read.return_value = json.dumps({'ok': False, 'error': 'invalid_auth'}).encode()
                with self.assertRaisesRegex(RuntimeError, 'invalid_auth'):
                    check_slack_auth('private-token', 'book/secondary')
            self.assertIn('invalid_auth', summary.read_text())
            self.assertNotIn('private-token', summary.read_text() + output.getvalue())
            self.assertEqual(request.call_args.args[0].full_url, 'https://slack.com/api/auth.test')

    def test_success_does_not_log_identity_response(self):
        with patch('slack_health.urllib.request.urlopen') as request, patch('slack_health.report_health') as report:
            request.return_value.__enter__.return_value.read.return_value = b'{"ok":true,"user":"private identity"}'
            check_slack_auth('fake', 'dlab/secondary')
            report.assert_called_once_with('dlab/secondary', 'auth.test succeeded')
