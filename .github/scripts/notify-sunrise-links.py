"""Send a link correction without claiming to have checked live availability."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

links = json.loads(Path('sunrise_booking_links.json').read_text())['2026-09-24']
for train, url in links.items():
    with urlopen(url, timeout=30) as response:
        page = response.read().decode('utf-8')
    match = re.search(r'window.location.replace\((".*?")\);', page)
    target = json.loads(match.group(1)) if match else ''
    if urlsplit(target).hostname != 'e5489.jr-odekake.net' or 'inputDate=20260924&' not in target:
        raise RuntimeError('Published booking redirect is invalid')

text = ('🚆 サンライズ：予約リンクを修正しました\n'
        '2026/09/24 岡山22:34 → 東京09/25 07:08\n'
        '旧TinyURLは使わず、管理下の中継ページからJR公式の予約画面へ転送します。以前の通知ではなく、以下の新しいリンクをご利用ください。\n')
text += '\n'.join(f'<{url}|{train}の予約画面へ>' for train, url in links.items())
text += '\n※リンクの修正案内です。現在の空席を確認した通知ではありません。受付時間外やメンテナンス中は予約画面が開けない場合があります。'
payload = {'channel': 'C0C2LSTJD1T', 'text': text, 'unfurl_links': False,
           'blocks': [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}},
                      {'type': 'actions', 'elements': [
                          {'type': 'button', 'action_id': f'booking_{index}',
                           'text': {'type': 'plain_text', 'text': f'{train}の予約画面へ'}, 'url': url}
                          for index, (train, url) in enumerate(links.items())]}]}
request = Request('https://slack.com/api/chat.postMessage', data=json.dumps(payload).encode(),
                  headers={'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN'],
                           'Content-Type': 'application/json; charset=utf-8'})
with urlopen(request, timeout=30) as response:
    result = json.load(response)
if not result.get('ok'):
    raise RuntimeError('Slack delivery failed: ' + result.get('error', 'unknown'))
print('Corrected booking links delivered:', result['channel'], result['ts'])
