#!/usr/bin/env python3
"""
SEIBU FAST SPORTS FIELD（品川プリンスホテル）ピックルボール 空き監視スクリプト

平日(月〜金)の 19:00 / 20:00 開始の枠（夜メニュー 18:00~22:00 50分間）について、
予約受付ウィンドウ内（約2週間）の空き状況を TableCheck のカート検証APIで確認し、
前回状態(pickleball_shinagawa_state.json)と比較して変化があれば Slack へ通知する。

方式:
  TableCheck の空き検索グリッドは施設全体（ゴルフブース含む）の空きを返すため、
  ピックルボール限定の空きは「カートにメニューを積んだ状態での日時検証」でしか
  正確に判定できない。POST /v2/booking/cart でカートを作成し、対象日時ごとに
  PUT /v2/booking/cart/{id} (orders=[ピックルボール50分]) を投げて
  availability.code を見る:
    success          -> 空きあり
    other_time       -> その時刻は満席（代替時刻が返る）
    max_time_cutoff  -> 予約受付ウィンドウ外（それ以降の日付は打ち切り）
  ※カートは予約ではない（決済まで進めない限り何も確定しない）。

実行間隔:
  ワークフロー自体は既存の15分毎cronに相乗りするが、30分間隔で十分なため
  「時刻の分が 0-14 または 30-44 のときだけ実行」するゲートを持つ
  （cron-job.org は毎回ほぼ同じ分に発火するため、実質1回おき=30分毎になる）。
  環境変数 SHINAGAWA_FORCE が非空ならゲートを無視して必ず実行。

依存: requests
環境変数:
  SLACK_BOT_TOKEN    (必須) 既存と共用。chat.postMessage で投稿
  SLACK_CHANNEL_PB   (任意) 投稿先チャンネルID。未設定なら #reservation の C0BJ3ETJ1H7
  SHINAGAWA_FORCE    (任意) 非空なら30分ゲートを無視して実行
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, date, timedelta

import requests

RESERVE_PAGE_URL = "https://www.tablecheck.com/ja/seibu-fast-sports/reserve/menu"
CART_URL = "https://production-booking.tablecheck.com/v2/booking/cart"
SHOP_SLUG = "seibu-fast-sports"
# ピックルボール【平日】18:00~22:00 50分間 ¥11,000 のメニューID
MENU_ITEM_ID = "69b23febef8de2d820d25791"
PAX_ADULT = 2

TARGET_HOURS_JST = [19, 20]       # 19:00 / 20:00 開始
WINDOW_DAYS = 15                  # 受付ウィンドウ側で打ち切られるので広めでよい
STATE_FILE = os.path.join(os.path.dirname(__file__),
                          "pickleball_shinagawa_state.json")
DEFAULT_CHANNEL = "C0BJ3ETJ1H7"   # #reservation
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")


def _cart_body(session_ref, start_at_utc, orders):
    return {
        "shop_slug": SHOP_SLUG, "service_mode": "dining",
        "pax_adult": PAX_ADULT, "pax_senior": 0, "pax_child": 0, "pax_baby": 0,
        "start_at": start_at_utc, "manual_duration": None, "seat_types": [],
        "smoking": "none", "service_category_id": None, "purpose": None,
        "room_name": "", "visit_history": None, "special_request": "",
        "orders": orders, "answers": [], "membership_auth_id": None,
        "referrer_url": "", "allow_marketing": False,
        "use_experience_page": False, "is_smartpay_requested": False,
        "voucher_ids": [], "locale": "ja", "session_ref": session_ref,
    }


def _jst_to_utc_iso(d, hour_jst):
    """date + JST時 -> UTC ISO文字列（TableCheckはUTCで受ける）"""
    return f"{d.isoformat()}T{hour_jst - 9:02d}:00:00Z"


def scan_availability():
    """平日19/20時の空き枠を 'YYYY-MM-DD HH:MM' の集合で返す。"""
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    session_ref = str(uuid.uuid4())
    s = requests.Session()

    # カート作成（予約ではない。決済まで進めない限り何も確定しない）
    r = s.post(CART_URL, headers=headers, timeout=30,
               json=_cart_body(session_ref,
                               _jst_to_utc_iso(date.today() + timedelta(days=1), 19), []))
    r.raise_for_status()
    cart = r.json().get("cart") or {}
    cart_id = cart.get("id") or cart.get("_id")
    if not cart_id:
        raise RuntimeError(f"cart作成失敗: {list(r.json().keys())}")

    found = set()
    today = date.today()
    orders = [{"menu_item_id": MENU_ITEM_ID, "qty": 1}]
    cutoff = False
    checked = 0

    for i in range(WINDOW_DAYS + 1):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:      # 平日のみ
            continue
        for hour in TARGET_HOURS_JST:
            body = _cart_body(session_ref, _jst_to_utc_iso(d, hour), orders)
            r = s.put(f"{CART_URL}/{cart_id}", headers=headers,
                      json=body, timeout=30)
            r.raise_for_status()
            code = (r.json().get("availability") or {}).get("code")
            checked += 1
            if code == "success":
                found.add(f"{d.isoformat()} {hour:02d}:00")
            elif code == "max_time_cutoff":
                cutoff = True
                break
            time.sleep(0.3)       # 行儀よく
        if cutoff:
            break

    if checked == 0:
        raise RuntimeError("1件もチェックできなかった（受付ウィンドウ判定異常）")
    print(f"[{datetime.now()}] 品川scan: checked={checked} "
          f"空き={sorted(found)}", file=sys.stderr)
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

    lines = ["🏓 ピックルボール品川(SEIBU FAST SPORTS) 空き枠アラート"]
    if opened:
        lines.append("\n🟢 空きが出ました:")
        lines += [f"・{fmt(s)}" for s in sorted(opened)]
    if filled:
        lines.append("\n🔴 満席に戻りました:")
        lines += [f"・{fmt(s)}" for s in sorted(filled)]
    lines.append(f"\n{RESERVE_PAGE_URL}")
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
    # 30分ゲート: 15分毎cronの1回おきに実行（分が 0-14 / 30-44 のとき実行）
    if not os.environ.get("SHINAGAWA_FORCE"):
        if (datetime.now().minute // 15) % 2 == 1:
            print(f"[{datetime.now()}] 30分ゲート: このサイクルはスキップ")
            return

    try:
        current = scan_availability()
    except Exception as e:
        print(f"[{datetime.now()}] 品川: 取得失敗のため通知・記録をスキップ: {e}",
              file=sys.stderr)
        sys.exit(0)

    previous = load_previous()
    opened = current - previous
    filled = previous - current

    if opened or filled:
        notify_slack(opened, filled)
        print(f"[{datetime.now()}] 品川通知: 空く{sorted(opened)} / 満席復帰{sorted(filled)}")
    else:
        print(f"[{datetime.now()}] 品川: 変化なし (現在の空き: {sorted(current)})")

    save_state(current)


if __name__ == "__main__":
    main()
