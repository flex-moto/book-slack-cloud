#!/usr/bin/env python3
"""
PICKLEBALL ONE GINZA SHIMBASHI コート予約 空き監視スクリプト（常時稼働版）

平日(月〜金)の 19:00 / 20:00 開始の枠について、直近2週間以内の空き状況を
ヘッドレスブラウザで読み取り、前回状態(state.json)と比較して変化があれば
Slack Incoming Webhook で通知する。

- 空き判定: グリッドセル内のアイコン i.icon-circle = 空き / i.icon-ban = 満席
- 日時取得: セル内 input[type=checkbox] の data-day(YYYYMMDD) と data-sttime(HHMM)
- 週送り:   a.cal__title__arrow 内の i.icon-arrow-circle-right をクリック

依存: playwright  (pip install playwright && playwright install chromium)
環境変数:
  SLACK_BOT_TOKEN    (必須) 既存リポジトリと共用。chat.postMessage で投稿
  SLACK_CHANNEL_PB   (任意) 投稿先チャンネルID。未設定なら #reservation の C0BJ3ETJ1H7
"""

import json
import os
import sys
from datetime import datetime, date

from playwright.sync_api import sync_playwright

RESERVE_URL = (
    "https://reserva.be/pboneginza/reserve"
    "?mode=service_staff&search_evt_no=aaeJwzNDQwsbQEAAQoATk"
)
TARGET_TIMES = {"1900", "2000"}   # 19時・20時開始（=19〜21時）
WINDOW_DAYS = 14                  # 直近2週間
WEEKS_TO_SCAN = 2                 # 表示週 + 翌週
STATE_FILE = os.path.join(os.path.dirname(__file__), "pickleball_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"   # #reservation
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def read_available_from_page(page):
    """現在表示中の週の、空きセル(data-day, data-sttime)一覧を返す。"""
    return page.eval_on_selector_all(
        ".cal-timeline__cell--data",
        """
        cells => cells
          .filter(c => c.querySelector('i.icon-circle'))
          .map(c => {
            const cb = c.querySelector('input[type=checkbox]');
            return cb ? {day: cb.getAttribute('data-day'),
                        sttime: cb.getAttribute('data-sttime')} : null;
          })
          .filter(Boolean)
        """,
    )


def scan_availability():
    """2週間ぶんの対象空き枠を 'YYYY-MM-DD HH:MM' の集合で返す。"""
    found = set()
    today = date.today()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.goto(RESERVE_URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(".cal-timeline__cell--data", timeout=30000)
        except Exception:
            # 診断: CI環境で何が返っているかを確認するための一時ログ
            try:
                html = page.content()
                body = page.inner_text("body")[:1500] if page.query_selector("body") else "(no body)"
            except Exception as ie:
                html, body = "", f"(dump failed: {ie})"
            print(f"[DEBUG] title={page.title()!r} url={page.url!r} "
                  f"len_html={len(html)} "
                  f"cells={len(page.query_selector_all('.cal-timeline__cell--data'))}",
                  file=sys.stderr)
            print("[DEBUG] body(head1500):\n" + body, file=sys.stderr)
            raise

        for week in range(WEEKS_TO_SCAN):
            if week > 0:
                # 翌週へ（右矢印）
                arrow = page.query_selector(
                    "a.cal__title__arrow:has(i.icon-arrow-circle-right)"
                )
                if not arrow:
                    break
                arrow.click()
                page.wait_for_timeout(1500)
                page.wait_for_selector(".cal-timeline__cell--data", timeout=30000)

            for cell in read_available_from_page(page):
                day, sttime = cell.get("day"), cell.get("sttime")
                if not day or not sttime or len(day) != 8:
                    continue
                if False:  # TEMP-TEST: 通知経路検証のため全時間帯を対象化（要リバート）
                    continue
                d = date(int(day[0:4]), int(day[4:6]), int(day[6:8]))
                # 平日のみ / 直近2週間以内 / 過去でない
                if d.weekday() >= 5:
                    continue
                delta = (d - today).days
                if delta < 0 or delta > WINDOW_DAYS:
                    continue
                found.add(f"{d.isoformat()} {sttime[:2]}:{sttime[2:]}")
        browser.close()
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
