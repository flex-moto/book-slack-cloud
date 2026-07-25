#!/usr/bin/env python3
"""
タイムズカーシェア 空き監視スクリプト（Cookie再利用版）

指定ステーションのタイムテーブルから「空きあり(水色)」枠を監視し、前回状態
(timescar_state.json)と比較して新たに空きが出たら Slack へ通知する。
既存の monitor.py（PICKLEBALL ONE GINZA 監視）と同じ作法・構成を踏襲。

■ ログイン必須 & reCAPTCHA のため Cookie 再利用方式
  空き状況ページ(reserve/input.jsp)は会員ログインの内側にあり、ログイン
  フォームは reCAPTCHA(invisible v2)で保護されているため自動ログインは行わない。
  代わりに「手動ログイン済みのセッションCookie」を環境変数で受け取り再利用する。
  Cookie が失効するとログイン/エラーページへ飛ばされるため、その場合は状態を
  更新せず「Cookie更新が必要」通知のみ出して終了する。

■ 実DOM調査で確定した事実（2026-07 時点、ログイン済みブラウザで確認）
  - 空き状況ページ直リンク: /view/reserve/input.jsp?scd=<STATION>&carBaseModelNm=&searchFlg=
    （Cookieさえ有効なら transit エラーなく直接開ける）
  - 車両ごとに <table class="time">。空き枠セルは td.timelinedot.vacant
      .vacant      = rgb(102,204,255) 水色 = 空きあり   ← 検知対象
      .full        = rgb(255,153,160) 満席
      .impossible  = rgb(211,211,211) 予約不可
      .maintenance = rgb(255,242,255) メンテナンス
  - タイムテーブルは「現在時刻起点の約12時間・15分刻み」の窓。1時間=4列(dot,dot,dot,space)。
    列の日付は td.time(colspan)、時刻は td.timeline(colspan=4=1時間)から復元。
  - 日付を進めるには「次のタイムテーブルへ」= JS doSearchNextTimetableJs() を押す（1回=次の窓）。
    → 遠い将来日(例 2週間先)を狙うと押下回数が多く重い。近未来監視が実用的。
  - 参考: ステーション例 LM25 = 利尻富士観光ホテル駐車場（夏季限定営業）。
          車両例 ベーシック／ハスラー(carId 1259165) / ベーシック／ルークス(1202623)。
          タイムズ本体にも「空き待ち設定」機能あり（別途）。

依存: playwright  (pip install playwright && playwright install chromium)

環境変数:
  SLACK_BOT_TOKEN          (必須) 既存リポジトリと共用。chat.postMessage で投稿
  SLACK_CHANNEL_TIMESCAR   (任意) 投稿先チャンネルID。未設定なら #reservation
  TIMESCAR_COOKIE          (必須) 手動ログイン後のCookie。 "name=value; name2=value2" 形式
  TIMESCAR_STATION         (任意) ステーションコード(scd)。未設定なら LM25（利尻富士観光ホテル駐車場）
  TIMESCAR_CARS            (任意) 監視対象車両名の一部。カンマ区切り。未指定なら全車両
  TIMESCAR_TARGET_DATE     (任意) "YYYY-MM-DD"。指定するとその日付までタイムテーブルを送って監視。
                                  未指定なら現在窓（近未来 約12時間）のみ監視（推奨・軽量）。
  TIMESCAR_PAGES_AHEAD     (任意) TARGET_DATE未指定時に追加で先読みする窓数（既定0）
  TIMESCAR_MAX_PAGES       (任意) TARGET_DATE到達までに送る最大窓数の上限（既定40）
  TIMESCAR_TIMES           (任意) 監視対象の時台 "HH" のカンマ区切り。未指定なら全時台
  TIMESCAR_DEBUG           (任意) "1" で取得内容を標準出力へダンプし通知しない
"""

import json
import os
import sys
from datetime import datetime, date

from playwright.sync_api import sync_playwright

# ─────────────────────────────────────────────────────────────
# 対象URL / 定数
# ─────────────────────────────────────────────────────────────
BASE = "https://share.timescar.jp"
LOGIN_HOST = "api.timesclub.jp"          # ここへ飛ばされたら＝Cookie失効
ERROR_MARK = "invalidTransitError"       # 遷移切れ

STATE_FILE = os.path.join(os.path.dirname(__file__), "timescar_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"          # #reservation（ピックルボールと共通）
COOKIE_URL = BASE
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


# ─────────────────────────────────────────────────────────────
# 設定（環境変数で上書き可）
# ─────────────────────────────────────────────────────────────
def _envlist(key, default):
    raw = os.environ.get(key, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items if items else default


STATION_CD    = os.environ.get("TIMESCAR_STATION", "LM25").strip() or "LM25"
TARGET_CARS   = _envlist("TIMESCAR_CARS", [])            # 空=全車両
TARGET_DATE   = os.environ.get("TIMESCAR_TARGET_DATE", "").strip()   # "YYYY-MM-DD" or ""
PAGES_AHEAD   = int(os.environ.get("TIMESCAR_PAGES_AHEAD", "0") or 0)
MAX_PAGES     = int(os.environ.get("TIMESCAR_MAX_PAGES", "40") or 40)
TARGET_HOURS  = set(_envlist("TIMESCAR_TIMES", []))      # 空=全時台（"HH"）
DEBUG = os.environ.get("TIMESCAR_DEBUG") == "1"

RESERVE_URL = f"{BASE}/view/reserve/input.jsp?scd={STATION_CD}&carBaseModelNm=&searchFlg="


class LoginRequired(Exception):
    pass


# ─────────────────────────────────────────────────────────────
# ブラウザ内でタイムテーブルを解析（列ジオメトリから日時を復元）
#   返り値: [{car, carId, date:"MM月DD日", hour:"HH"} ...]（vacantセルのみ、時台粒度）
# ─────────────────────────────────────────────────────────────
PARSE_JS = r"""
() => {
  const out = [];
  const tables = document.querySelectorAll('table.time');
  tables.forEach(t => {
    // 車両ID（timelinedot を含む要素のid）と車両ラベル
    const dot0 = t.querySelector('td.timelinedot');
    const carId = dot0 ? (dot0.closest('[id]') ? dot0.closest('[id]').id : '') : '';
    const label = (t.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40);

    // 日付列（colspan で 48 列に展開）
    const dateCells = [...t.querySelectorAll('td.time')];
    const dateByCol = [];
    dateCells.forEach(c => { for (let i = 0; i < (c.colSpan || 1); i++) dateByCol.push(c.textContent.trim()); });

    // 時刻列（colspan=4=1時間 で 48 列に展開）
    const timeCells = [...t.querySelectorAll('td.timeline')];
    const hourByCol = [];
    timeCells.forEach(c => {
      const hh = (c.textContent.trim().match(/(\d{1,2}):/) || [,''])[1];
      for (let i = 0; i < (c.colSpan || 1); i++) hourByCol.push(hh);
    });

    // ドット行（timelinedot / timelinespace が並ぶ行）
    const rows = [...t.rows];
    const dotRow = rows.find(r => [...r.cells].some(c => /timelinedot|timelinespace/.test(c.className)));
    if (!dotRow) return;
    [...dotRow.cells].forEach((c, i) => {
      if (!/timelinedot/.test(c.className)) return;      // space（区切り）は無視
      if (!/vacant/.test(c.className)) return;           // 空き(水色)のみ
      out.push({ car: label, carId: carId, date: dateByCol[i] || '', hour: hourByCol[i] || '' });
    });
  });
  // 時台粒度で重複除去
  const seen = new Set(), uniq = [];
  out.forEach(o => { const k = [o.carId, o.date, o.hour].join('|'); if (!seen.has(k)) { seen.add(k); uniq.push(o); } });
  return uniq;
}
"""

# 現在表示中の窓の「最終日付」を "MM月DD日" で取得（TARGET_DATE到達判定用）
LASTDATE_JS = r"""
() => {
  const ds = [...document.querySelectorAll('table.time td.time')].map(c => c.textContent.trim());
  return ds.length ? ds[ds.length - 1] : '';
}
"""


def _mmdd_to_iso(mmdd, base_year, base_month):
    """'08月10日' → 'YYYY-MM-DD'。月が基準月より小さければ翌年に繰り上げ。"""
    m = mmdd.replace("月", "-").replace("日", "")
    try:
        mm, dd = [int(x) for x in m.split("-")]
    except ValueError:
        return None
    year = base_year + 1 if mm < base_month else base_year
    return date(year, mm, dd).isoformat()


def _goto_grid(page):
    page.goto(RESERVE_URL, wait_until="networkidle", timeout=60000)
    if LOGIN_HOST in page.url or ERROR_MARK in page.url:
        raise LoginRequired()
    page.wait_for_selector("table.time", timeout=30000)


def _next_timetable(page):
    """「次のタイムテーブルへ」を押して次の窓へ。押せなければ False。"""
    ok = page.evaluate(
        "() => { if (typeof doSearchNextTimetableJs === 'function') { doSearchNextTimetableJs(); return true; } "
        "const b = document.querySelector('[id$=doSearchNextTimetable]'); if (b) { b.click(); return true; } return false; }"
    )
    if not ok:
        return False
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_selector("table.time", timeout=30000)
    return True


def _collect(page):
    """現在窓の vacant を 'car | YYYY-MM-DD HH時' 集合で返す。"""
    today = date.today()
    rows = page.evaluate(PARSE_JS)
    out = set()
    for r in rows:
        iso = _mmdd_to_iso(r.get("date", ""), today.year, today.month)
        hour = r.get("hour", "")
        if not iso or not hour:
            continue
        if TARGET_HOURS and hour not in TARGET_HOURS:
            continue
        if TARGET_CARS and not any(c in r.get("car", "") for c in TARGET_CARS):
            continue
        out.add(f"{r.get('car','')} | {iso} {hour}時")
    return out


def scan_availability():
    """対象の vacant 枠集合を返す。Cookie失効時は LoginRequired。"""
    jar = cookies_from_env()
    if not jar:
        raise RuntimeError("TIMESCAR_COOKIE 未設定（手動ログイン後のCookieが必要）")

    found = set()
    today = date.today()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(jar)
        page = context.new_page()
        _goto_grid(page)

        if DEBUG:
            print("===== TIMESCAR DEBUG =====")
            print("URL:", page.url)
            print("tables:", page.eval_on_selector_all("table.time", "els => els.length"))
            print("vacant(now):", page.eval_on_selector_all("td.timelinedot.vacant", "els => els.length"))
            print("parsed(now):", json.dumps(page.evaluate(PARSE_JS), ensure_ascii=False))

        found |= _collect(page)

        if TARGET_DATE:
            # TARGET_DATE を含む窓まで送る
            pages = 0
            while pages < MAX_PAGES:
                last = _mmdd_to_iso(page.evaluate(LASTDATE_JS), today.year, today.month)
                if last and last >= TARGET_DATE:
                    break
                if not _next_timetable(page):
                    break
                pages += 1
                found |= _collect(page)
            # TARGET_DATE の枠だけに絞る
            found = {s for s in found if f" {TARGET_DATE} " in s}
        else:
            for _ in range(max(0, PAGES_AHEAD)):
                if not _next_timetable(page):
                    break
                found |= _collect(page)

        browser.close()
    return found


def cookies_from_env():
    """TIMESCAR_COOKIE("a=1; b=2")を Playwright add_cookies 用の配列へ。"""
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
        print(f"[{datetime.now()}] Cookie失効: ログイン/エラーページへ。状態は更新せず通知のみ。",
              file=sys.stderr)
        notify_cookie_expired()
        sys.exit(0)
    except Exception as e:
        # 取得失敗時は状態を更新せず終了（取りこぼし・誤検知防止）＝monitor.pyと同作法
        print(f"[{datetime.now()}] 取得失敗のため通知・記録をスキップ: {e}", file=sys.stderr)
        sys.exit(0)

    if DEBUG:
        print("DEBUG collected:", json.dumps(sorted(current), ensure_ascii=False))
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
