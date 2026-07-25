#!/usr/bin/env python3
"""
タイムズカーシェア 空き監視スクリプト（Cookie再利用版）

指定ステーションの指定日（既定: 2026-08-10 / 08-11）・時台（既定: 08〜19時＝8:00〜20:00）
の「空きあり(水色)」枠を監視し、前回状態(timescar_state.json)と比較して新たに空きが
出たら Slack へ通知する。既存の monitor.py（PICKLEBALL 監視）と同じ作法・構成を踏襲。

■ ログイン必須 & reCAPTCHA のため Cookie 再利用方式
  空き状況ページ(reserve/input.jsp)は会員ログインの内側にあり、ログインフォームは
  reCAPTCHA(invisible v2)で保護されているため自動ログインは行わない。代わりに
  「手動ログイン済みのセッションCookie」を環境変数で受け取り再利用する。Cookieが失効
  するとログイン/エラーページへ飛ばされるため、その場合は状態を更新せず「Cookie更新が
  必要」通知のみ出して終了する。

■ 実DOM調査で確定した事実（2026-07 時点、ログイン済みブラウザで確認）
  - 空き状況ページ直リンク: /view/reserve/input.jsp?scd=<STATION>&carBaseModelNm=&searchFlg=
    （Cookieが有効なら transit エラーなく直接開ける。開いた直後は「現在時刻起点」の窓）
  - 車両ごとに <table class="time">。1時間=4列(dot,dot,dot,space)、15分刻み。
    セル状態は class で判定:
      .vacant      = rgb(102,204,255) 水色 = 空きあり   ← 検知対象（td.timelinedot.vacant）
      .full        = rgb(255,153,160) 満席
      .impossible  = rgb(211,211,211) 予約不可
      .maintenance = rgb(255,242,255) メンテナンス
  - 1つの窓は「12時間ぶん」。日付は td.time(colspan)、時刻は td.timeline(colspan=4=1時間)で復元。
  - 日付選択やdoCheckでは窓は動かない。窓を進めるのは「次のタイムテーブルへ」=
    JS doSearchNextTimetableJs() のみ（1回=12時間前進）。→ 遠い将来日は繰り返し送って到達する。
  - 既定ステーション LM25 = 利尻富士観光ホテル駐車場（夏季限定営業 6/1〜10月末）。
    車両: ベーシック／ハスラー(1259165) / ベーシック／ルークス(1202623)。

依存: playwright  (pip install playwright && playwright install chromium)

環境変数:
  SLACK_BOT_TOKEN          (必須) 既存リポジトリと共用。chat.postMessage で投稿
  SLACK_CHANNEL_TIMESCAR   (任意) 投稿先チャンネルID。未設定なら #reservation
  TIMESCAR_COOKIE          (必須) 手動ログイン後のCookie。 "name=value; name2=value2" 形式
  TIMESCAR_STATION         (任意) ステーションコード(scd)。未設定なら LM25
  TIMESCAR_CARS            (任意) 監視対象車両名の一部。カンマ区切り。未指定なら全車両
  TIMESCAR_TARGET_DATES    (任意) 監視対象日 "YYYY-MM-DD" のカンマ区切り。未設定なら 2026-08-10,2026-08-11
  TIMESCAR_TIMES           (任意) 監視する時台 "HH" のカンマ区切り。未設定なら 08〜19（=8:00〜20:00）
  TIMESCAR_MAX_PAGES       (任意) タイムテーブルを送る最大回数の上限（既定 60）
  TIMESCAR_DEBUG           (任意) "1" で取得内容を標準出力へダンプし通知しない
"""

import json
import os
import sys
from datetime import datetime, date

from playwright.sync_api import sync_playwright

BASE = "https://share.timescar.jp"
LOGIN_HOST = "api.timesclub.jp"          # ここへ飛ばされたら＝Cookie失効
ERROR_MARK = "invalidTransitError"       # 遷移切れ

STATE_FILE = os.path.join(os.path.dirname(__file__), "timescar_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"          # #reservation（ピックルボールと共通）
COOKIE_URL = BASE
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _envlist(key, default):
    raw = os.environ.get(key, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items if items else default


# ─── 設定（環境変数で上書き可）。既定はユーザー指定の固定値 ───
STATION_CD   = os.environ.get("TIMESCAR_STATION", "LM25").strip() or "LM25"
TARGET_CARS  = _envlist("TIMESCAR_CARS", [])                     # 空=全車両
TARGET_DATES = _envlist("TIMESCAR_TARGET_DATES", ["2026-08-10", "2026-08-11"])
# 08〜19時台（19時台=19:00〜20:00）＝利用 8:00〜20:00 をカバー
TARGET_HOURS = set(_envlist("TIMESCAR_TIMES", [f"{h:02d}" for h in range(8, 20)]))
MAX_PAGES    = int(os.environ.get("TIMESCAR_MAX_PAGES", "60") or 60)
DEBUG = os.environ.get("TIMESCAR_DEBUG") == "1"

RESERVE_URL = f"{BASE}/view/reserve/input.jsp?scd={STATION_CD}&carBaseModelNm=&searchFlg="


class LoginRequired(Exception):
    pass


# ブラウザ内でタイムテーブルを解析（列カウンタで日時を復元。callback index非依存で堅牢）
# 返り値: [{car, carId, date:"MM月DD日", hour:"HH"} ...]（vacantセルのみ、時台粒度で重複除去）
PARSE_JS = r"""
() => {
  const out = [], seen = new Set();
  const tables = document.querySelectorAll('table.time');
  for (let ti = 0; ti < tables.length; ti++) {
    const t = tables[ti];
    const dot0 = t.querySelector('td.timelinedot');
    const carId = dot0 && dot0.closest('[id]') ? dot0.closest('[id]').id : '';
    const label = (t.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 40);

    const dateByCol = [];
    const dcells = t.querySelectorAll('td.time');
    for (let a = 0; a < dcells.length; a++) {
      const n = dcells[a].colSpan || 1;
      for (let k = 0; k < n; k++) dateByCol.push(dcells[a].textContent.trim());
    }
    const hourByCol = [];
    const hcells = t.querySelectorAll('td.timeline');
    for (let a = 0; a < hcells.length; a++) {
      const m = hcells[a].textContent.trim().match(/(\d{1,2}):/);
      const hh = m ? m[1] : '';
      const n = hcells[a].colSpan || 1;
      for (let k = 0; k < n; k++) hourByCol.push(hh);
    }
    let dotRow = null;
    const rows = t.rows;
    for (let a = 0; a < rows.length; a++) {
      const cs = rows[a].cells;
      for (let b = 0; b < cs.length; b++) {
        if (/timelinedot|timelinespace/.test(cs[b].className)) { dotRow = rows[a]; break; }
      }
      if (dotRow) break;
    }
    if (!dotRow) continue;
    const cells = dotRow.cells;
    let col = 0;
    for (let a = 0; a < cells.length; a++) {
      const cls = cells[a].className;
      if (/timelinedot/.test(cls)) {
        if (/vacant/.test(cls)) {
          const key = carId + '|' + (dateByCol[col] || '') + '|' + (hourByCol[col] || '');
          if (!seen.has(key)) {
            seen.add(key);
            out.push({ car: label, carId: carId, date: dateByCol[col] || '', hour: hourByCol[col] || '' });
          }
        }
      }
      col++;
    }
  }
  return out;
}
"""

# 現在窓の最も早い日付 "MM月DD日"（到達判定用）
EARLIEST_JS = ("() => { const d = [...document.querySelectorAll('table.time td.time')]"
               ".map(c => c.textContent.trim()); return d.length ? d[0] : ''; }")


def _mmdd_to_iso(mmdd, base_year, base_month):
    """'08月10日' → 'YYYY-MM-DD'。月が基準月より小さければ翌年へ繰り上げ。"""
    if not mmdd:
        return None
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
    """「次のタイムテーブルへ」で次の12時間窓へ。押せなければ False。"""
    ok = page.evaluate(
        "() => { if (typeof doSearchNextTimetableJs === 'function') { doSearchNextTimetableJs(); return true; } "
        "const b = document.querySelector('[id$=doSearchNextTimetable]'); if (b) { b.click(); return true; } return false; }"
    )
    if not ok:
        return False
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_selector("table.time", timeout=30000)
    return True


def _collect(page, today):
    """現在窓の vacant を、対象日・対象時台・対象車両で絞って
    'car | YYYY-MM-DD HH時' 集合で返す。"""
    out = set()
    for r in page.evaluate(PARSE_JS):
        iso = _mmdd_to_iso(r.get("date", ""), today.year, today.month)
        hour = r.get("hour", "")
        car = r.get("car", "")
        if not iso or not hour:
            continue
        if TARGET_DATES and iso not in TARGET_DATES:
            continue
        if TARGET_HOURS and hour not in TARGET_HOURS:
            continue
        if TARGET_CARS and not any(c in car for c in TARGET_CARS):
            continue
        out.add(f"{car} | {iso} {hour}時")
    return out


def scan_availability():
    """対象の vacant 枠集合を返す。Cookie失効時は LoginRequired。"""
    jar = cookies_from_env()
    if not jar:
        raise RuntimeError("TIMESCAR_COOKIE 未設定（手動ログイン後のCookieが必要）")

    today = date.today()
    max_target = max(TARGET_DATES) if TARGET_DATES else None
    found = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(jar)
        page = context.new_page()
        _goto_grid(page)

        found |= _collect(page, today)
        pages = 0
        while max_target and pages < MAX_PAGES:
            earliest = _mmdd_to_iso(page.evaluate(EARLIEST_JS), today.year, today.month)
            if earliest and earliest > max_target:
                break
            if not _next_timetable(page):
                break
            pages += 1
            found |= _collect(page, today)

        if DEBUG:
            print("===== TIMESCAR DEBUG =====")
            print("URL:", page.url, "| pages sent:", pages)
            print("collected:", json.dumps(sorted(found), ensure_ascii=False))

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
    lines = ["🚗 タイムズカーシェア 空き枠アラート（利尻富士観光ホテル駐車場）"]
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
