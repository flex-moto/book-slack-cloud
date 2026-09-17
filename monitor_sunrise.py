"""Read-only Sunrise availability monitor; never selects or reserves a seat."""
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright

URL = 'https://www.jr-odekake.net/goyoyaku/campaign/sunriseseto_izumo/form.html'
JST = ZoneInfo('Asia/Tokyo')
DEPARTURE = datetime(2026, 9, 24, 22, 34, tzinfo=JST)
STATE = Path('sunrise_state.json')



def classify(rows):
    """Pair headings with statuses; ignore explanatory legends outside table."""
    if len(rows) != 2 or len(rows[0]) != len(rows[1]):
        raise RuntimeError('Unexpected availability table shape')
    available = {}
    for heading, status in zip(*rows):
        if not any(kind in heading for kind in ['普通車指定席', 'A寝台', 'B寝台']):
            raise RuntimeError('Unknown accommodation heading')
        if any(mark in status for mark in ['空席あり', '空席残りわずか']):
            available[heading.strip()] = status.strip()
        elif not any(mark in status for mark in ['残席なし', '座席の設定なし']):
            raise RuntimeError('Unrecognized availability; refusing to report sold out')
    return available


def scan():
    available = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale='ja-JP')
        for train in ['サンライズ瀬戸', 'サンライズ出雲']:
            page.goto(URL, wait_until='load')
            page.locator('#member-no').click()
            for selector, label in [('jsSelectYear', '2026年'), ('jsSelectMonth', '9月'), ('jsSelectDay', '24日'), ('jsSelectHour', '22'), ('jsSelectMinute', '00'), ('jsSelectTrainType', train), ('inputDepartStName', '岡山'), ('inputArriveStName', '東京')]:
                page.locator('#' + selector).select_option(label=label)
            page.locator('#radio-box-1').check()
            for selector, label in [('jsSelectDay', '24日'), ('jsSelectHour', '22'), ('jsSelectMinute', '00'), ('jsSelectTrainType', train), ('inputDepartStName', '岡山'), ('inputArriveStName', '東京')]:
                selected = page.locator('#' + selector + ' option:checked').inner_text()
                if selected.strip() != label:
                    raise RuntimeError('Search form reset unexpectedly: ' + selector)
            page.locator('#submitButton').click()
            try:
                page.get_by_role('heading', name='新規予約 経路・設備選択').wait_for()
            except Exception:
                print('Public search error page:', page.locator('body').inner_text()[:6000], flush=True)
                raise
            body = page.locator('body').inner_text()
            compact = ''.join(body.split())
            if not all(text in compact for text in [train, '岡山', '東京', '22:34', '07:08', '9月24日']):
                raise RuntimeError('Unexpected date, train or route: ' + compact[:5000])
            table = page.get_by_text('特急' + train, exact=True).locator('xpath=following::table[1]')
            rows = table.evaluate("e => Array.from(e.rows, r => Array.from(r.cells, c => (c.innerText + ' ' + Array.from(c.querySelectorAll('img'), i => i.alt).join(' ')).trim()))")
            print(train, json.dumps(rows, ensure_ascii=False), flush=True)
            for category, status in classify(rows).items():
                available[train + ' / ' + category] = status
        browser.close()
    return available


def main():
    now = datetime.now(JST)
    if now >= DEPARTURE:
        print('Departure passed; monitoring ended.')
        return
    if now.hour < 5 or (now.hour == 23 and now.minute >= 30):
        print('Outside booking service hours; skipped.')
        return
    current = scan()
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    opened = {key: value for key, value in current.items() if key not in previous}
    if os.environ.get('SUNRISE_NOTIFY') != '1':
        print('Dry run: new availability:', json.dumps(opened, ensure_ascii=False))
        return
    if opened:
        lines = ['🚆 サンライズ 空席アラート', '2026/9/24(木) 岡山22:34 → 東京9/25(金)07:08／大人1名', f'確認: {now:%m/%d %H:%M} JST']
        for key, status in opened.items():
            lines.append('・' + key.replace('普通車指定席', 'ノビノビ座席') + '：' + status)
        lines.extend(['A寝台＝シングルデラックス。B寝台はシングルツイン／シングル／ソロ／サンライズツインの総合表示で、空いている個室の種類は予約ページでご確認ください。', '料金：この検索画面では未表示。予約画面でご確認ください。', 'サンライズツインは1名利用でも2名分の料金券が必要です。', f'<{URL}|e5489で空席を確認して予約する>', '空席は変動します。自動予約・購入は行っていません。'])
        response = requests.post('https://slack.com/api/chat.postMessage', headers={'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN']}, json={'channel': os.environ.get('SLACK_CHANNEL_PB') or 'C0BJ3ETJ1H7', 'text': '\n'.join(lines), 'unfurl_links': False}, timeout=30)
        response.raise_for_status()
        if not response.json().get('ok'):
            raise RuntimeError('Slack delivery failed: ' + response.json().get('error', 'unknown'))
    # Only persist after a complete scan and successful delivery.
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
