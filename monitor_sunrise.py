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
HEALTH = Path('sunrise_health.json')
DEFAULT_CHANNEL = 'C0C2LSTJD1T'


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
    if len(rows) != 2 or not rows[0] or len(rows[0]) != len(rows[1]):
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


def booking_url(train, departure=DEPARTURE):
    # Slack re-encodes non-UTF-8 (%89 etc.) bytes in e5489's Shift-JIS URL.
    # These ASCII redirects were verified to preserve the exact search URL.
    links = json.loads(Path(__file__).with_name('sunrise_booking_links.json').read_text())
    try:
        return links[departure.strftime('%Y-%m-%d')][train]
    except KeyError:
        raise ValueError('Create and verify a booking redirect for this date and train') from None


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
            expected = {'普通車指定席 禁煙席', 'B寝台 禁煙個室', 'B寝台 喫煙個室', 'A寝台 禁煙個室', 'A寝台 喫煙個室'}
            if not rows or {heading.strip() for heading in rows[0]} != expected or len(rows[0]) != len(expected):
                raise RuntimeError('Incomplete accommodation categories; refusing to report seats filled')
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


def send_alert(opened, departure=DEPARTURE, *, closed=None, status_update=False, test=False, confirmed_at=None):
    now = confirmed_at or datetime.now(JST)
    closed = closed or {}
    if not opened and not closed and not status_update:
        raise ValueError("No observed availability change to notify")
    arrival = departure + timedelta(days=1)
    title = '通知先の設定完了・現在の空席状況' if status_update else ('空席状況の変化' if closed else '空席アラート')
    lines = [('【実地テスト】' if test else '') + '🚆 サンライズ ' + title, f'{departure:%Y/%m/%d} 岡山22:34 → 東京{arrival:%m/%d}07:08／大人1名', f'確認: {now:%m/%d %H:%M} JST']
    if test:
        lines.append('通知動作の確認用です。本番の9月24日の空席通知ではありません。')
    if status_update:
        lines.append('このチャンネルに空席が出たとき・埋まったときの両方を通知します（約15分間隔で確認）。')
        if not opened:
            lines.append('現在、監視対象の空席はありません。')
    if opened:
        lines.append('空席があります：' if status_update else '空席が出ました：')
    for key, status in opened.items():
        lines.append('・' + key.replace('普通車指定席', 'ノビノビ座席') + '：' + status)
    if closed:
        lines.append('前回空いていた以下の席は埋まりました：')
        for key in closed:
            lines.append('・' + key.replace('普通車指定席', 'ノビノビ座席') + '：空席なし')
    trains = sorted({key.split(' / ')[0] for key in set(opened) | set(closed)})
    if status_update:
        trains = ['サンライズ瀬戸', 'サンライズ出雲']
    for train in trains:
        lines.append(f'<{booking_url(train, departure)}|{train}：{departure.month}/{departure.day} 岡山→東京の予約画面へ>')
    lines.append('リンク先は日付・区間・列車を指定済みの「新規予約 経路・設備選択」です。空席のある設備を選び「選択する」からお進みください。満席の場合は選択できません。')
    lines.extend(['A寝台＝シングルデラックス。B寝台はシングルツイン／シングル／ソロ／サンライズツインの総合表示で、空いている個室の種類は予約ページでご確認ください。', '料金：この検索画面では未表示。予約画面でご確認ください。', 'サンライズツインは1名利用でも2名分の料金券が必要です。', '空席は変動します。自動予約・購入は行っていません。'])
    text = '\n'.join(lines)
    payload = {
        'channel': os.environ.get('SLACK_CHANNEL_SUNRISE') or DEFAULT_CHANNEL,
        'text': text, 'unfurl_links': False,
        'blocks': [{'type': 'section', 'text': {'type': 'mrkdwn', 'text': text}}],
    }
    if trains:
        payload['blocks'].append({'type': 'actions', 'elements': [
            {'type': 'button', 'action_id': f'book_sunrise_{index}',
             'text': {'type': 'plain_text', 'text': f'{train}の予約画面へ'},
             'url': booking_url(train, departure)}
            for index, train in enumerate(trains)
        ]})
    return post_slack(payload)


def post_slack(payload):
    response = requests.post('https://slack.com/api/chat.postMessage', headers={'Authorization': 'Bearer ' + os.environ['SLACK_BOT_TOKEN']}, json=payload, timeout=30)
    response.raise_for_status()
    if not response.json().get('ok'):
        raise RuntimeError('Slack delivery failed: ' + response.json().get('error', 'unknown'))
    print('Sunrise notification delivered to channel:', response.json().get('channel'), flush=True)
    return response.json()


def record_health(*, busy, now):
    """Persist incident notification state separately from seat availability."""
    if os.environ.get('SUNRISE_NOTIFY') != '1':
        return
    health = json.loads(HEALTH.read_text()) if HEALTH.exists() else {}
    if busy:
        if not health:
            health = {'since': now.isoformat(), 'alerted': False}
        since = datetime.fromisoformat(health['since'])
        if now - since >= timedelta(hours=1) and not health['alerted']:
            post_slack({
                'channel': os.environ.get('SLACK_CHANNEL_SUNRISE') or DEFAULT_CHANNEL,
                'text': ('⚠️ サンライズ：空席確認ができていません\n'
                         f'予約サイトの混雑が続き、{since:%m/%d %H:%M} JSTから1時間以上確認できていません。\n'
                         '約15分後に再確認します。前回の空席情報は保持しています。'),
                'unfurl_links': False,
            })
            health['alerted'] = True
    else:
        if health.get('alerted'):
            post_slack({
                'channel': os.environ.get('SLACK_CHANNEL_SUNRISE') or DEFAULT_CHANNEL,
                'text': f'✅ サンライズ：監視が復旧しました\n{now:%m/%d %H:%M} JSTに空席確認が成功しました。',
                'unfurl_links': False,
            })
        health = {}
    # Failed Slack delivery raises before updating the notification marker.
    HEALTH.write_text(json.dumps(health, ensure_ascii=False, indent=2) + '\n')


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
    except BookingServiceBusy:
        print('Booking site busy after retries; defer to next scheduled check. Seat state preserved.', flush=True)
        record_health(busy=True, now=datetime.now(JST))
        return
    except BookingServiceClosed as error:
        message = f'Skipped: {error}. Availability was not checked; previous state preserved.'
        print(message, flush=True)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
                summary.write(message + '\n')
        return
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    opened = {key: value for key, value in current.items() if key not in previous}
    closed = {key: value for key, value in previous.items() if key not in current}
    if os.environ.get('SUNRISE_NOTIFY') != '1':
        print('Dry run: availability changes:', json.dumps({'opened': opened, 'closed': closed}, ensure_ascii=False))
        return
    record_health(busy=False, now=datetime.now(JST))
    status_update = os.environ.get('SUNRISE_STATUS_UPDATE') == '1'
    if opened or closed or status_update:
        send_alert(current if status_update else opened, closed=closed, status_update=status_update, confirmed_at=datetime.now(JST))
    # Only persist after a complete scan and successful delivery.
    STATE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
