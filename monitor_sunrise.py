"""Read-only Sunrise availability monitor; never selects or reserves a seat."""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout

URL = 'https://www.jr-odekake.net/goyoyaku/campaign/sunriseseto_izumo/form.html'
JST = ZoneInfo('Asia/Tokyo')
DEPARTURE = datetime(2026, 9, 24, 22, 34, tzinfo=JST)
STATE = Path('sunrise_state.json')


class BookingServiceClosed(RuntimeError):
    pass


class BookingServiceBusy(RuntimeError):
    pass


def check_service_message(body):
    if '20100941' in body or 'ただいま受付時間外です' in body:
        raise BookingServiceClosed('e5489 is outside reception hours or under maintenance')
    if '20100946' in body or '混雑中です' in body:
        raise BookingServiceBusy('e5489 is temporarily busy')



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


def search_url(train, departure=DEPARTURE):
    # Exact public result URL observed in the e5489 browser UI.
    train_code = '%BB%BE%C4%20%20000' if train == 'サンライズ瀬戸' else '%BB%B2%BD%D3%20000'
    return ('https://e5489.jr-odekake.net/e5489/cspc/CBDayTimeArriveSelRsvMyDiaPC?'
        f'inputDepartStName=%89%AA%8ER&inputArriveStName=%93%8C%8B%9E&inputType=0&inputDate={departure:%Y%m%d}&inputHour=22&inputMinute=00&inputUniqueDepartSt=1&inputUniqueArriveSt=1&inputSearchType=2&inputTransferDepartStName1=%89%AA%8ER&inputTransferArriveStName1=%93%8C%8B%9E&inputTransferDepartStUnique1=1&inputTransferArriveStUnique1=1&inputTransferTrainType1=0001&inputSpecificTrainType1=2&inputSpecificBriefTrainKana1='
        + train_code + '&SequenceType=0&inputReturnUrl=goyoyaku/campaign/sunriseseto_izumo/form.html&RTURL=https://www.jr-odekake.net/goyoyaku/campaign/sunriseseto_izumo/form.html&')


def scan_once(departure=DEPARTURE):
    available = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale='ja-JP')
        for train in ['サンライズ瀬戸', 'サンライズ出雲']:
            page.goto(search_url(train, departure), wait_until='load')
            check_service_message(page.locator('body').inner_text())
            try:
                page.get_by_role('heading', name='新規予約 経路・設備選択').wait_for()
            except BrowserTimeout:
                check_service_message(page.locator('body').inner_text())
                raise
            body = page.locator('body').inner_text()
            compact = ''.join(body.split())
            if not all(text in compact for text in [train, '岡山', '東京', '22:34', '07:08', f'{departure.month}月{departure.day}日']):
                raise RuntimeError('Unexpected date, train or route: ' + compact[:5000])
            table = page.get_by_text('特急' + train, exact=True).locator('xpath=following::table[1]')
            rows = table.evaluate("e => Array.from(e.rows, r => Array.from(r.cells, c => (c.innerText + ' ' + Array.from(c.querySelectorAll('img'), i => i.alt).join(' ')).trim()))")
            print(train, json.dumps(rows, ensure_ascii=False), flush=True)
            for category, status in classify(rows).items():
                available[train + ' / ' + category] = status
        browser.close()
    return available


def scan(departure=DEPARTURE):
    for attempt in range(3):
        try:
            return scan_once(departure)
        except BookingServiceClosed:
            # A maintenance closure is not a sold-out result. Never alter state.
            raise
        except (BrowserTimeout, BookingServiceBusy):
            if attempt == 2:
                raise
            delay = 30 * (attempt + 1)
            print(f'Search temporarily unavailable; retrying after {delay} seconds.', flush=True)
            time.sleep(delay)


def send_alert(opened, departure=DEPARTURE, *, test=False, confirmed_at=None):
    now = confirmed_at or datetime.now(JST)
    if not opened:
        raise ValueError("No observed availability to notify")
    arrival = departure + timedelta(days=1)
    lines = [('【実地テスト】' if test else '') + '🚆 サンライズ 空席アラート', f'{departure:%Y/%m/%d} 岡山22:34 → 東京{arrival:%m/%d}07:08／大人1名', f'確認: {now:%m/%d %H:%M} JST']
    if test:
        lines.append('通知動作の確認用です。本番の9月24日の空席通知ではありません。')
    for key, status in opened.items():
        lines.append('・' + key.replace('普通車指定席', 'ノビノビ座席') + '：' + status)
    for train in sorted({key.split(' / ')[0] for key in opened}):
        lines.append(f'<{search_url(train, departure)}|{train}：{departure.month}/{departure.day} 岡山→東京の検索結果を開く>')
    lines.extend(['A寝台＝シングルデラックス。B寝台はシングルツイン／シングル／ソロ／サンライズツインの総合表示で、空いている個室の種類は予約ページでご確認ください。', '料金：この検索画面では未表示。予約画面でご確認ください。', 'サンライズツインは1名利用でも2名分の料金券が必要です。', f'<{URL}|e5489で空席を確認して予約する>', '空席は変動します。自動予約・購入は行っていません。'])
    response = requests.post('https://slack.com/api/chat.postMessage', headers={'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN']}, json={'channel': os.environ.get('SLACK_CHANNEL_PB') or 'C0BJ3ETJ1H7', 'text': '\n'.join(lines), 'unfurl_links': False}, timeout=30)
    response.raise_for_status()
    if not response.json().get('ok'):
        raise RuntimeError('Slack delivery failed: ' + response.json().get('error', 'unknown'))
    return response.json()


def main():
    now = datetime.now(JST)
    if now >= DEPARTURE:
        print('Departure passed; monitoring ended.')
        return
    minute = now.hour * 60 + now.minute
    if not (5 <= minute < 110 or 330 <= minute < 1430):
        print('Outside booking service hours; skipped.')
        return
    try:
        current = scan()
    except BookingServiceClosed as error:
        message = f'Skipped: {error}. Availability was not checked; previous state preserved.'
        print(message, flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                summary.write(message + '\n')
        return
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    opened = {key: value for key, value in current.items() if key not in previous}
    if os.environ.get('SUNRISE_NOTIFY') != '1':
        print('Dry run: new availability:', json.dumps(opened, ensure_ascii=False))
        return
    if opened:
        send_alert(opened, confirmed_at=now)
    # Only persist after a complete scan and successful delivery.
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
