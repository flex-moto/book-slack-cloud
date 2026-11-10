"""Read-only Slack authentication checks and credential-free Actions summaries."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request


def report_health(target, message, error=False):
    # Only pass fixed labels and API error codes, never tokens or API responses.
    line = f'{target}: {message}'
    print(('::error::' if error else '') + line, flush=True)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with Path(summary).open('a', encoding='utf-8') as stream:
            stream.write(line + '\n\n')


def check_slack_auth(token, target):
    request = urllib.request.Request(
        'https://slack.com/api/auth.test', data=b'',
        headers={'Authorization': f'Bearer {token}'}, method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        report_health(target, 'auth.test request failed', error=True)
        raise RuntimeError(f'{target}: Slack authentication check unavailable') from None
    if not result.get('ok'):
        code = result.get('error', 'unknown')
        # Do not emit arbitrary remote response text in annotations or summaries.
        if not isinstance(code, str) or not code.replace('_', '').isalnum():
            code = 'unknown'
        report_health(target, f'auth.test failed ({code})', error=True)
        raise RuntimeError(f'{target}: Slack authentication failed ({code})')
    report_health(target, 'auth.test succeeded')
