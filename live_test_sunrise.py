"""One-off real-availability test using the production scanner and sender."""
import json
import os
from datetime import datetime
from pathlib import Path

import requests
import monitor_sunrise as monitor


def main():
    departure = datetime(2026, 10, 14, 22, 34, tzinfo=monitor.JST)
    before = monitor.STATE.read_bytes() if monitor.STATE.exists() else None
    availability = monitor.scan(departure)
    if not availability:
        raise RuntimeError('No real availability now; no test alert was sent')
    result = monitor.send_alert(availability, departure, test=True)
    receipt = {'date': departure.isoformat(), 'availability': availability,
               'channel': result['channel'], 'ts': result['ts'], 'slack_ok': result['ok']}
    response = requests.get('https://slack.com/api/chat.getPermalink',
                            headers={'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN']},
                            params={'channel': result['channel'], 'message_ts': result['ts']}, timeout=30)
    response.raise_for_status()
    permalink = response.json()
    if permalink.get('ok'):
        receipt['permalink'] = permalink['permalink']
    after = monitor.STATE.read_bytes() if monitor.STATE.exists() else None
    if before != after or monitor.DEPARTURE.isoformat() != '2026-09-24T22:34:00+09:00':
        raise RuntimeError('Production configuration/state changed unexpectedly')
    receipt['production_state_unchanged'] = True
    Path('sunrise_live_test_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
