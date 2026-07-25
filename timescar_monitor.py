#!/usr/bin/env python3
"""
タイムズカーシェア コート予約 空き監視スクリプト（Cookie再利用版）

指定ステーション・日付・時間帯・車両クラスの「空きあり(水色)」枠を監視し、
前回状態(timescar_state.json)と比較して新たに空きが出たら Slack へ通知する。
既存の monitor.py（PICKLEBALL ONE GINZA 監視）と同じ作法・構成を踏襲。

■ ピックルボールとの違い＝ログイン必須
  タイムズの空き状況ページ(reserve/input.jsp)は会員ログインの内側にあり、
  さらにログインフォームは reCAPTCHA で保護されているため、ヘッドレスでの
  自動ログインは行わない（規約・bot検知の観点でも不可）。
  代わりに「手動ログイン済みのセッションCookie」を環境変数で受け取り再利用する。
  Cookie が失効するとログインページへ飛ばされるため、その場合は状態を更新せず
  「Cookie更新が必要」である旨だけ通知して終了する。

依存: playwright  (pip install playwright && playwright install chromium)

環境変数:
  SLACK_BOT_TOKEN          (必須) 既存リポジトリと共用。chat.postMessage で投稿
  SLACK_CHANNEL_TIMESCAR   (任意) 投稿先チャンネルID。未設定なら #reservation
  TIMESCAR_COOKIE          (必須) 手動ログイン後のCookie。 "name=value; name2=value2" 形式
  TIMESCAR_STATION         (任意) 監視対象ステーション（コード or 名称の一部）。カンマ区切りで複数可
  TIMESCAR_DATES           (任意) 監視対象日付 "YYYY-MM-DD" のカンマ区切り
  TIMESCAR_TIMES           (任意) 監視対象の開始時刻 "HH:MM" のカンマ区切り。未指定なら全時間帯
  TIMESCAR_CLASSES         (任意) 監視対象の車両クラス名の一部。カンマ区切り。未指定なら全クラス
  TIMESCAR_DEBUG           (任意) "1" にすると、取得したグリッドのHTML断片を標準出力へダンプし通知は行わない。
                                  ★初回はこれで実DOM構造を確認し、下の SELECTORS / AVAILABLE_MARKERS を確定する。
"""

import json
import os
import sys
from datetime import datetime, date

from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────────────────────
# 対象URL
# ─────────────────────────────────────────────────────────────
RESERVE_URL = "https://share.timescar.jp/view/reserve/input.jsp"
LOGIN_HOST = "api.timesclub.jp"   # ここへ飛ばされたら＝Cookie失効
COOKIE_URL = "https://share.timescar.jp"

STATE_FILE = os.path.join(os.path.dirname(__file__), "timescar_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"   # #reservation（ピックルボールと共通）
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]

# ─────────────────────────────────────────────────────────────
# 監視対象（デフォルトはスクショの例。環境変数で上書き可能）
#   ※ 利尻島系ステーションの正式コード/名称は要確認。暫定で名称の一部を置く。
# ─────────────────────────────────────────────────────────────
def _envlist(key, default):
    raw = os.environ.get(key, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items if items else default

TARGET_STATIONS = _envlist("TIMESCAR_STATION", ["利尻"])          # 要確認
TARGET_DATES    = _envlist("TIMESCAR_DATES",   ["2026-08-10"])    # 要確認
TARGET_TIMES    = set(_envlist("TIMESCAR_TIMES", []))              # 空=全時間帯
TARGET_CLASSES  = _envlist("TIMESCAR_CLASSES", [])                # 空=全クラス
DEBUG = os.environ.get("TIMESCAR_DEBUG") == "1"

# ─────────────────────────────────────────────────────────────
# ★★ ここは実DOMを見て確定する（初回 TIMESCAR_DEBUG=1 のダンプで確認）★★
#   空き状況グリッドのセレクタと「空きあり(水色)」判定の目印。
#   凡例: 水色=空きあり / 赤(ピンク)=空きなし / オレンジ=予約済み(自身) /
#         グレー=予約不可 / 黒=メンテナンス
# ─────────────────────────────────────────────────────────────
SELECTORS = {
    # 車両クラスごとのタイムテーブル行/表を囲む要素（暫定）
    "grid_root": "table.reserve, .timetable, .cal-timeline",
    # 時間帯セル（暫定）
    "cell": "td, .cell",
}
# セルが「空きあり(水色)」であることを示す class 名 or 背景色の目印（暫定・要確認）
AVAILABLE_MARKERS = [
    "vacant", "available", "empty", "aki", "status-o", "o",
    # 背景色フォールバック（水色系）
    "#00b0f0", "#33ccff", "#99e6ff", "aqua", "lightblue",
]


def parse_grid(page):
    """
    現在ページの空き状況グリッドから、条件に合う「空きあり」枠を
    'STATION | YYYY-MM-DD HH:MM | CLASS' の集合で返す。

    ★ 実DOM確定までは暫定実装。TIMESCAR_DEBUG=1 で構造をダンプして
      SELECTORS / AVAILABLE_MARKERS を合わせ込む前提。
    """
    return set(page.evaluate(
        """
        (cfg) => {
          const { markers, times, classes, stations } = cfg;
          const norm = s => (s || '').toLowerCase();
          const isAvail = (el) => {
            const cls = norm(el.className);
            const bg  = norm(getComputedStyle(el).backgroundColor);
            const styleAttr = norm(el.getAttribute('style'));
            return markers.some(m => cls.includes(m) || bg.includes(m) || styleAttr.includes(m));
          };
          const out = new Set();
          const cells = document.querySelectorAll('td,[class*="cell"],[data-sttime],[data-time]');
          cells.forEach(c => {
            if (!isAvail(c)) return;
            // セル/近傍から日付・時刻・クラス・ステーションを推定（暫定）
            const t = c.getAttribute('data-sttime') || c.getAttribute('data-time')
                    || (c.textContent || '').trim();
            const day = c.getAttribute('data-day') || '';
            const cls = (c.closest('[data-class],[data-carclass]') || {}).getAttribute
                        ? (c.closest('[data-class],[data-carclass]').getAttribute('data-class')
                           || c.closest('[data-class],[data-carclass]').getAttribute('data-carclass')) : '';
            out.add([stations[0]||'', day, t, cls].join(' | '));
          });
          return [...out];
        }
        """,
        {
            "markers": AVAILABLE_MARKERS,
            "times": sorted(TARGET_TIMES),
            "classes": TARGET_CLASSES,
            "stations": TARGET_STATIONS,
        },
    ))


def cookies_from_env():
    """TIMESCAR_COOKIE(\"a=1; b=2\")を Playwright add_cookies 用の配列へ。"""
    raw = os.environ.get("TIMESCAR_COOKIE", "").strip()
    if not raw:
        return []
    jar = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        jar.append({"name": name.strip(), "value": value.strip(), "url": COOKIE_URL})
    return jar


def scan_availability():
    """対象空き枠を集合で返す。Cookie失効時は LoginRequired を送出。"""
    jar = cookies_from_env()
    if not jar:
        raise RuntimeError("TIMESCAR_COOKIE 未設定（手動ログイン後のCookieが必要）")

    found = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(jar)
        page = context.new_page()
        page.goto(RESERVE_URL, wait_until="networkidle", timeout=60000)

        if LOGIN_HOST in page.url:
            browser.close()
            raise LoginRequired()

        if DEBUG:
            # 実DOM確認用ダンプ（セレクタ確定に使う）
            html = page.content()
            print("===== TIMESCAR GRID DUMP (先頭8000字) =====")
            print(html[:8000])
            print("===== /DUMP =====")
            browser.close()
            return set()

        found = parse_grid(page)
        browser.close()

    # 対象日付・時刻・クラスで絞り込み（サーバ側で全部は出せないため後段で）
    def keep(slot):
        s = slot.lower()
        if TARGET_DATES and not any(d in slot for d in TARGET_DATES):
            return False
        if TARGET_TIMES and not any(t in slot for t in TARGET_TIMES):
            return False
        if TARGET_CLASSES and not any(c.lower() in s for c in TARGET_CLASSES):
            return False
        return True

    return {s for s in found if keep(s)}


class LoginRequired(Exception):
    pass


def load_previous():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(slots):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(slots), f, ensure_ascii=False, indent=1)


def _slack_post(text):
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_TIMESCAR") or DEFAULT_CHANNEL
    if not token:
        print("SLACK_BOT_TOKEN 未設定のため通知をスキップ", file=sys.stderr)
        return
    import urllib.request

    payload = json.dumps({"channel": channel, "text": text}).encode("utf-8")
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
        print(f"Slack投稿失敗: {resp.get('error')}", file=sys.stderr)


def notify_slack(opened, filled):
    lines = ["🚗 タイムズカーシェア 空き枠アラート"]
    if opened:
        lines.append("\n🟢 空きが出ました:")
        lines += [f"・{s}" for s in sorted(opened)]
    if filled:
        lines.append("\n🔴 満席に戻りました:")
        lines += [f"・{s}" for s in sorted(filled)]
    lines.append(f"\n{RESERVE_URL}")
    _slack_post("\n".join(lines))


def notify_cookie_expired():
    _slack_post(
        "⚠️ タイムズカーシェア監視: セッションCookieが失効しました。\n"
        "手動でログインし直し、GitHub Secrets の TIMESCAR_COOKIE を更新してください。"
    )


def main():
    try:
        current = scan_availability()
    except LoginRequired:
        print(f"[{datetime.now()}] Cookie失効: ログインページへリダイレクト。状態は更新せず通知のみ。",
              file=sys.stderr)
        notify_cookie_expired()
        sys.exit(0)
    except Exception as e:
        # 取得失敗時は状態を更新せず終了（取りこぼし・誤検知防止）＝monitor.pyと同作法
        print(f"[{datetime.now()}] 取得失敗のため通知・記録をスキップ: {e}", file=sys.stderr)
        sys.exit(0)

    if DEBUG:
        return

    previous = load_previous()
    opened = current - previous          # 満席→空き
    filled = previous - current          # 空き→満席

    if opened or filled:
        notify_slack(opened, filled)
        print(f"[{datetime.now()}] 通知: 空き{sorted(opened)} / 満席復帰{sorted(filled)}")
    else:
        print(f"[{datetime.now()}] 変化なし (現在の空き: {sorted(current)})")

    save_state(current)


if __name__ == "__main__":
    main()
