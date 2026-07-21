#!/usr/bin/env python3
"""
PICKLEBALL ONE GINZA SHIMBASHI コート予約 空き監視スクリプト（常時稼働版）

平日(月〜金)の 19:00 / 20:00 開始の枠について、直近2週間以内の空き状況を
予約サイトの内部API(AjaxSearch)から取得し、前回状態(state.json)と比較して
変化があれば Slack(chat.postMessage) で通知する。

方式:
  予約カレンダーの空き枠は、ページ表示時に POST /AjaxSearch (cmd=get_new_institution)
  が返す JSON の table_html 内に描画される。ブラウザ(Playwright)を使わず、この API を
  requests で直接叩いて table_html をパースする（ヘッドレスだと描画されない問題を回避）。

- 空き判定: セル(div.cal-timeline__cell--data)内に i.icon-circle があれば空き
- 日時取得: セル内 input[type=checkbox] の data-day(YYYYMMDD) と data-sttime(HHMM)
- 週送り:   レスポンス JSON の target_next_week(YYYY/MM/DD) を次の target_date に使う

依存: requests
環境変数:
  SLACK_BOT_TOKEN    (必須) 既存リポジトリと共用。chat.postMessage で投稿
  SLACK_CHANNEL_PB   (任意) 投稿先チャンネルID。未設定なら #reservation の C0BJ3ETJ1H7
"""

import json
import os
import re
import sys
from datetime import datetime, date

import requests

RESERVE_URL = (
    "https://reserva.be/pboneginza/reserve"
    "?mode=service_staff&search_evt_no=aaeJwzNDQwsbQEAAQoATk"
)
AJAX_URL = "https://reserva.be/AjaxSearch"
RESERVE_BUS_CD = "325310"          # 施設(事業者)コード
RESERVE_IST_NO = "110499"          # サービス(区画)番号
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

TARGET_TIMES = {"1900", "2000"}   # 19時・20時開始（=19〜21時）
WINDOW_DAYS = 14                  # 直近2週間
WEEKS_TO_SCAN = 2                 # 表示週 + 翌週
STATE_FILE = os.path.join(os.path.dirname(__file__), "pickleball_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"   # #reservation
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

_DAY_RE = re.compile(r'data-day="(\d{8})"')
_ST_RE = re.compile(r'data-sttime="(\d{4})"')


def _fetch_week(session, target_date):
    """target_date(YYYY-MM-DD)を含む週の AjaxSearch レスポンス(JSON)を返す。"""
    body = {
        "cmd": "get_new_institution",
        "reserve_bus_cd": RESERVE_BUS_CD,
        "reserve_ist_no": RESERVE_IST_NO,
        "target_date": target_date,
        "mode": "",
        "month_week": "week",
        "datetime_max_days": "1",
        "select_timeorday": "1",
        "price_type_no": "0",
    }
    headers = {
        "User-Agent": USER_AGENT,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": RESERVE_URL,
        "Origin": "https://reserva.be",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ja,en;q=0.9",
    }
    r = session.post(AJAX_URL, data=body, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _parse_available(table_html):
    """table_html から空き(icon-circle)セルの (day8, sttime4) 一覧を返す。"""
    out = []
    for chunk in re.split(r'(?=<div[^>]*cal-timeline__cell--data)', table_html):
        if "cal-timeline__cell--data" not in chunk:
            continue
        if "icon-circle" not in chunk:      # icon-ban = 満席 はスキップ
            continue
        d = _DAY_RE.search(chunk)
        s = _ST_RE.search(chunk)
        if d and s:
            out.append((d.group(1), s.group(1)))
    return out


def scan_availability():
    """2週間ぶんの対象空き枠を 'YYYY-MM-DD HH:MM' の集合で返す。"""
    found = set()
    today = date.today()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    # Cookie 等の取得のため予約ページを一度 GET（任意）
    try:
        session.get(RESERVE_URL, timeout=30)
    except requests.RequestException:
        pass

    target = today.isoformat()
    seen_targets = set()
    total_cells = 0
    total_avail = 0

    for _ in range(WEEKS_TO_SCAN):
        data = _fetch_week(session, target)
        table_html = data.get("table_html", "") or ""
        total_cells += len(re.findall(r"cal-timeline__cell--data", table_html))

        for day, sttime in _parse_available(table_html):
            total_avail += 1
            if len(day) != 8:
                continue
            if sttime not in TARGET_TIMES:
                continue
            d = date(int(day[0:4]), int(day[4:6]), int(day[6:8]))
            # 平日のみ / 直近2週間以内 / 過去でない
            if d.weekday() >= 5:
                continue
            delta = (d - today).days
            if delta < 0 or delta > WINDOW_DAYS:
                continue
            found.add(f"{d.isoformat()} {sttime[:2]}:{sttime[2:]}")

        nxt = data.get("target_next_week")   # 'YYYY/MM/DD'
        if not nxt:
            break
        target = nxt.replace("/", "-")
        if target in seen_targets:
            break
        seen_targets.add(target)

    print(f"[{datetime.now()}] scan: cells={total_cells} available={total_avail} "
          f"target(19/20時・平日・2週間)={sorted(found)}", file=sys.stderr)
    return found


def load_previous():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(slots):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(slots), f, ensure_ascii=False, indent=1)


def fmt(slot):
    """'2026-07-22 19:00' -> '7/22(水) 19:00'"""
    d_str, t = slot.split(" ")
    d = date.fromisoformat(d_str)
    return f"{d.month}/{d.day}({WEEKDAYS_JP[d.weekday()]}) {t}"


def notify_slack(opened, filled):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_PB") or DEFAULT_CHANNEL
    if not token:
        print("SLACK_BOT_TOKEN 未設定のため通知をスキップ", file=sys.stderr)
        return
    import urllib.request

    lines = ["🎾 ピックルボール銀座 空き枠アラート"]
    if opened:
        lines.append("\n🟢 空きが出ました:")
        lines += [f"・{fmt(s)}" for s in sorted(opened)]
    if filled:
        lines.append("\n🔴 満席に戻りました:")
        lines += [f"・{fmt(s)}" for s in sorted(filled)]
    lines.append(f"\n{RESERVE_URL}")
    payload = json.dumps(
        {"channel": channel, "text": "\n".join(lines)}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if not resp.get("ok"):
        # not_in_channel などはログに残す（アプリを #reservation に招待要）
        print(f"Slack投稿失敗: {resp.get('error')}", file=sys.stderr)


def main():
    try:
        current = scan_availability()
    except Exception as e:
        # 取得失敗時は状態を更新せず終了（取りこぼし・誤検知防止）
        print(f"[{datetime.now()}] 取得失敗のため通知・記録をスキップ: {e}",
              file=sys.stderr)
        sys.exit(0)

    previous = load_previous()
    opened = current - previous          # 満席→空き
    filled = previous - current          # 空き→満席

    if opened or filled:
        notify_slack(opened, filled)
        print(f"[{datetime.now()}] 通知: 空く{sorted(opened)} / 満席復帰{sorted(filled)}")
    else:
        print(f"[{datetime.now()}] 変化なし (現在の空き: {sorted(current)})")

    save_state(current)


if __name__ == "__main__":
    main()
