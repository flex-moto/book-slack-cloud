#!/usr/bin/env python3
"""12/19/2026 Reserve One court monitoring (JST)."""
import argparse
import json
import os
import sys
import time as time_module
from datetime import datetime, date, time
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from playwright.sync_api import sync_playwright, Error as PlaywrightError

TARGET = date(2026, 12, 19)
JST = ZoneInfo('Asia/Tokyo')
STATE = Path(__file__).with_name('pickleball_reserve_one_state.json')
FACILITIES = {
    'asics': ('ASICS PICKLEBALL CONNECT', 'https://rsv.pickle-one.com/pb1-asics-tokia/menus/43244f26-8220-4aa6-8773-7756983a7b8e', '2026-11-16T12:00:00+09:00', ['Aコート', 'Bコート']),
    'toyosu': ('PICKLEBALL PARK TOYOSU', 'https://rsv.pickle-one.com/pb1-toyosu/menus/0197f0b2-71e4-743f-bc29-500600164401', '2026-12-01T09:00:00+09:00', ['コートA', 'コートB', 'コートC', 'コートD']),
}

def validate_availability_response(body):
    result = next((line[2:] for line in body.splitlines() if line.startswith('1:')), None)
    if result is None:
        raise ValueError('unexpected availability response')
    data = json.loads(result)
    if isinstance(data, list):
        return
    if isinstance(data, dict) and all(isinstance(data.get(key), list) for key in ('reservations', 'closures', 'specialOpenings')):
        return
    raise ValueError('unexpected availability response')

def read_grid(page, courts):
    # Select an alternate start if the target is already the initial day.
    # Selecting an already-displayed range may use a client cache and emit no
    # request, so require a fresh, independently verifiable range instead.
    initial_target = bool(page.get_by_role('button', name='表示期間 12/19').count())
    start_day = 18 if initial_target else 19
    expected_from = f'2026-12-{start_day:02}'
    day_label = f'2026年12月{start_day}日' + ('金曜日' if initial_target else '土曜日')
    target_column = 1 if initial_target else 0
    page.get_by_role('button', name='表示期間').click()
    for _ in range(3):
        if page.get_by_role('button', name=day_label).count():
            break
        page.get_by_role('button', name='Go to the Next Month').click()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url == page.url and f'"from":"{expected_from}"' in (r.request.post_data or ''), timeout=20000) as pending:
        page.get_by_role('button', name=day_label).click()
    response = pending.value
    if response.status != 200:
        raise ValueError('availability request failed')
    body = response.text()
    validate_availability_response(body)
    page.get_by_role('button', name=f'表示期間 12/{start_day}').wait_for(timeout=15000)
    page.get_by_text('空き状況を読み込んでいます…').wait_for(state='hidden', timeout=15000)
    data = page.evaluate(r'''() => {
      const tables = [...document.querySelectorAll('table')];
      const header = tables.find(t => t.querySelector('thead') && t.innerText.includes('時間'));
      const grid = tables.find(t => t.querySelector('tbody tr td') && !t.querySelector('thead'));
      if (!header || !grid) throw Error('calendar tables missing');
      const names = [...header.querySelectorAll('thead tr')].at(-1).querySelectorAll('th,td');
      const rows = [...grid.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => ({text: td.innerText.trim(), labels:[...td.querySelectorAll('[aria-label]')].map(x=>x.getAttribute('aria-label')), title:td.querySelector('[title]')?.getAttribute('title') || ''})));
      const dates = [...header.querySelectorAll('thead tr:first-child th')].slice(1).map(x=>x.innerText.replace(/\s+/g,''));
      return {names:[...names].map(x=>x.innerText.trim()), dates, rows};
    }''')
    if len(data['dates']) != 7 or data['dates'][target_column] != '土19':
        raise ValueError('target date missing from calendar header: ' + repr(data['dates']))
    first_column = 1 + target_column * len(courts)
    if data['names'][first_column:first_column+len(courts)] != courts:
        raise ValueError('unexpected court headers: ' + repr(data['names'][:1+len(courts)]))
    slots = {}
    for row in data['rows']:
        if len(row) < first_column+len(courts) or not row[0]['text']:
            raise ValueError('incomplete row')
        time = row[0]['text'].replace(' ', '')
        for court, cell in zip(courts, row[first_column:first_column+len(courts)]):
            content = ' '.join(cell['labels']) + ' ' + cell['title']
            if '空き枠' in content: status = 'available'
            elif '予約済' in content: status = 'booked'
            elif '予約不可' in content: status = 'unavailable'
            else: raise ValueError('unknown slot: ' + repr(cell))
            slots[f'{time} {court}'] = status
    if len(slots) != 15 * len(courts) or {x.split()[0] for x in slots} != {f'{h:02}:00' for h in range(7, 22)}:
        raise ValueError('unexpected calendar hours or count')
    return slots

def eligible_slots(current, now):
    if now.date() != TARGET:
        return current
    return {k: v for k, v in current.items()
            if datetime.combine(TARGET, time.fromisoformat(k.split()[0]), JST) > now}

def slack(text):
    token = os.environ['SLACK_BOT_TOKEN']
    r = requests.post('https://slack.com/api/chat.postMessage', headers={'Authorization': 'Bearer '+token}, json={'channel': os.getenv('SLACK_CHANNEL_PB') or 'C0BJ3ETJ1H7', 'text':text}, timeout=20)
    r.raise_for_status()
    if not r.json().get('ok'): raise RuntimeError('Slack: '+str(r.json().get('error')))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--dry-run', action='store_true'); p.add_argument('--facility', choices=FACILITIES); args=p.parse_args()
    now=datetime.now(JST)
    # Last target slot begins at 21:00 JST; never report an already-started slot.
    if now >= datetime.combine(TARGET, time(21), JST):
        print('監視終了: 2026-12-19 21:00 JST')
        return
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True, executable_path=os.getenv('CHROMIUM_PATH') or None, args=['--no-sandbox'])
        for key,(name,url,opening,courts) in FACILITIES.items():
            if args.facility and key != args.facility: continue
            if now < datetime.fromisoformat(opening):
                print(f'{name}: 告知上の受付開始前 ({opening}); 実際の画面も確認')
            try:
                for attempt in range(2):
                    page=browser.new_page(locale='ja-JP', timezone_id='Asia/Tokyo')
                    try:
                        page.goto(url, wait_until='networkidle', timeout=45000)
                        current=read_grid(page,courts)
                        break
                    except PlaywrightError as exc:
                        if attempt or 'No data found for resource with given identifier' not in str(exc):
                            raise
                        print(f'{name}: 応答本文が失われたため新しいページで1回再取得', file=sys.stderr)
                        time_module.sleep(3)
                    finally:
                        page.close()
                current=eligible_slots(current, now)
                print(name, json.dumps(current,ensure_ascii=False))
                if args.dry_run: continue
                old=state.get(key,{})
                opened=sorted(k for k,v in current.items() if v == 'available' and old.get(k) != 'available')
                changed=sorted((k,current[k]) for k,v in old.items() if v=='available' and current.get(k) in ('booked','unavailable'))
                if opened or changed:
                    lines=[f'🏓 {name} 12/19(土) 予約状況']
                    if opened: lines += ['空き表示:', *['・'+x for x in opened]]
                    if changed: lines += ['空き表示が終了:', *['・'+x+'（'+('予約済' if s=='booked' else '予約不可')+'）' for x,s in changed]]
                    lines += ['状況は変わるため予約画面でご確認ください。', url]
                    slack('\n'.join(lines))
                state[key]=current
                STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
            except Exception as e:
                errors.append(f'{name}: {e}')
        browser.close()
    if errors:
        print('\n'.join(errors),file=sys.stderr)
        sys.exit(1)

if __name__=='__main__': main()
