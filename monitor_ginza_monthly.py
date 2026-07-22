#!/usr/bin/env python3
"""
PICKLEBALL ONE GINZA SHIMBASHI 毎月1日 9:00 の翌月分一斉開放 検知・通知スクリプト

この施設は毎月1日 午前9:00 に翌月分の予約が一斉開放される。
本スクリプトは毎月1日の 8:45〜9:30(JST) だけ動作し、9:00 まで待機したうえで
翌月の平日 19:00 / 20:00 開始枠（=19〜21時）の空きを45秒間隔でスキャンし、
開放を検知したら空き一覧を Slack に即通知する（月1回だけ）。

- 予約の確定は行わない（通知のみ）。予約はリンク先から手動で行う。
- 既存の monitor.py の AjaxSearch 取得・パース処理を再利用する。
- 通知済みかどうかは pickleball_monthly_state.json ({"notified": "YYYY-MM"}) で管理。
- GitHub Actions ランナーはUTCなので、時刻判定はJSTへ変換して行う。

環境変数:
  SLACK_BOT_TOKEN       (必須) chat.postMessage 用
  SLACK_CHANNEL_PB      (任意) 投稿先。未設定なら #reservation
  GINZA_MONTHLY_FORCE   (任意) 非空なら日付・時刻ゲートを無視して即スキャン＆通知（テスト用）
"""

import json
import os
import sys
import time
from datetime import datetime, date, timedelta

import requests

import monitor  # 既存の銀座監視（AjaxSearch取得・パース・定数を再利用）

STATE_FILE = os.path.join(os.path.dirname(__file__),
                          "pickleball_monthly_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"   # #reservation
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
JST = timedelta(hours=9)


def jst_now():
    return datetime.utcnow() + JST


def next_month_range(today):
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    first = date(y, m, 1)
    last = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) - timedelta(days=1)
    return first, last


def scan_next_month():
    """翌月の平日19/20時の空き枠集合と (first, last) を返す。"""
    first, last = next_month_range(jst_now().date())
    session = requests.Session()
    session.headers.update({"User-Agent": monitor.USER_AGENT})
    try:
        session.get(monitor.RESERVE_URL, timeout=30)
    except requests.RequestException:
        pass

    found = set()
    target = first.isoformat()
    seen = set()
    for _ in range(6):                     # 最大6週ぶん
        data = monitor._fetch_week(session, target)
        html = data.get("table_html") or ""
        for day, st in monitor._parse_available(html):
            if len(day) != 8 or st not in monitor.TARGET_TIMES:
                continue
            d = date(int(day[:4]), int(day[4:6]), int(day[6:8]))
            if d < first or d > last or d.weekday() >= 5:
                continue
            found.add(f"{d.isoformat()} {st[:2]}:{st[2:]}")
        nxt = data.get("target_next_week")     # 'YYYY/MM/DD'
        if not nxt:
            break
        target = nxt.replace("/", "-")
        if target in seen:
            break
        seen.add(target)
        if date.fromisoformat(target) > last:
            break
        time.sleep(0.5)
    return found, first, last


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(st):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def fmt(slot):
    d_str, t = slot.split(" ")
    d = date.fromisoformat(d_str)
    return f"{d.month}/{d.day}({WEEKDAYS_JP[d.weekday()]}) {t}"


def notify(found, first):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_PB") or DEFAULT_CHANNEL
    if not token:
        print("SLACK_BOT_TOKEN 未設定のため通知をスキップ", file=sys.stderr)
        return
    import urllib.request

    month_label = f"{first.month}月"
    if found:
        lines = [f"🎾📅 【毎月1日 開放】{month_label}分の平日19-21時 空き一覧 "
                 f"({len(found)}枠) — 早い者勝ちです！"]
        lines += [f"・{fmt(s)}" for s in sorted(found)]
        lines.append("\n▼ 今すぐ予約（要ログイン。キャンセルは3日前まで無料）")
    else:
        lines = [f"🎾📅 【毎月1日 開放チェック】9:20時点で{month_label}分の"
                 "平日19-21時の空きを検出できませんでした。"
                 "開放時刻の変更や即完売の可能性があります。手動でご確認ください。"]
    lines.append(monitor.RESERVE_URL)
    payload = json.dumps({"channel": channel,
                          "text": "\n".join(lines)}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage", data=payload,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        resp = json.loads(r.read().decode("utf-8"))
    if not resp.get("ok"):
        print(f"Slack投稿失敗: {resp.get('error')}", file=sys.stderr)


def main():
    force = os.environ.get("GINZA_MONTHLY_FORCE")
    now = jst_now()

    # 毎月1日の 8:45〜9:30 JST のみ動作（cronの8:53発火ランが9:00を跨いで担当する）
    if not force:
        minutes = now.hour * 60 + now.minute
        if now.day != 1 or not (8 * 60 + 45 <= minutes < 9 * 60 + 30):
            return

    first, _last = next_month_range(now.date())
    ym = first.strftime("%Y-%m")
    state = load_state()
    if state.get("notified") == ym:
        print(f"[{now}] {ym} は通知済み。スキップ")
        return

    # 9:00:05 JST まで待機
    if not force:
        while True:
            n = jst_now()
            if n.hour > 9 or (n.hour == 9 and (n.minute > 0 or n.second >= 5)):
                break
            time.sleep(5)

    deadline = jst_now().replace(hour=9, minute=20, second=0, microsecond=0)
    try:
        while True:
            found, first, last = scan_next_month()
            if found or force or jst_now() >= deadline:
                break
            print(f"[{jst_now()}] 開放待ち: まだ空きなし。45秒後に再試行",
                  file=sys.stderr)
            time.sleep(45)
    except Exception as e:
        print(f"[{jst_now()}] 月初スキャン失敗のため通知・記録をスキップ: {e}",
              file=sys.stderr)
        sys.exit(0)

    print(f"[{jst_now()}] 月初スキャン({ym}): {len(found)}枠 {sorted(found)}",
          file=sys.stderr)
    notify(found, first)
    state["notified"] = ym
    save_state(state)


if __name__ == "__main__":
    main()
