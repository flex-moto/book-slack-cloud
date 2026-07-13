#!/usr/bin/env python3
"""data/ 配下の Books と 読書メモ(Kindle) からランダムに1冊選び、
AIで紹介コメントを付けて Slack / WeChat に投稿する。GitHub Actions（Mac不要）で毎朝動く。

依存: Pillow（webp→png変換用。ローカルmacOSでは sips でも可）。

環境変数（GitHub Actions の Secrets などで渡す）:
  ANTHROPIC_API_KEY   … Anthropic API キー（必須）
  SLACK_BOT_TOKEN     … 1つ目のワークスペースの xoxb- Bot トークン（必須）
  SLACK_CHANNEL       … 1つ目の投稿先チャンネルID（必須。例 C0123ABCD）
  SLACK_BOT_TOKEN_2   … 2つ目のワークスペースの xoxb- Bot トークン（任意。両方揃うと2ワークスペースへ同時投稿）
  SLACK_CHANNEL_2     … 2つ目の投稿先チャンネルID（任意）
  NOTIFY_TARGETS      … 通知先（任意, 既定 slack。例: slack,wechat / wechat）
  WECHAT_PROVIDER     … WeChat通知サービス（任意, 既定 wxpusher。wxpusher / serverchan）
  WXPUSHER_APP_TOKEN  … WxPusher の appToken（WECHAT_PROVIDER=wxpusher の場合は必須）
  WXPUSHER_UIDS       … WxPusher の送信先UID（カンマ区切り。任意）
  WXPUSHER_TOPIC_IDS  … WxPusher の topicId（カンマ区切り。任意）
  SERVERCHAN_SENDKEY  … ServerChan の SendKey（WECHAT_PROVIDER=serverchan の場合は必須）
  BOOK_DATA_DIR       … 本データの基点（任意, 既定 ./data）
  BOOK_SUBDIRS        … 走査するサブフォルダ（任意, 既定 "Books,02_読書メモ"）
  ANTHROPIC_MODEL     … 使うモデル（任意, 既定 claude-opus-4-8 / 安いのは claude-haiku-4-5）
"""

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import uuid

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BOT_DIR, "posted.log")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8").strip()


def parse_csv_env(name):
    return [s.strip() for s in os.environ.get(name, "").split(",") if s.strip()]


def notify_targets():
    targets = parse_csv_env("NOTIFY_TARGETS") or ["slack"]
    return {t.lower() for t in targets}


def collect_slack_targets():
    """Slack投稿先（ワークスペース）を集める。Bot Tokenはワークスペース単位なので
    (token, channel) を1組=1ワークスペースとして、複数組を許可する。

    ・SLACK_BOT_TOKEN / SLACK_CHANNEL           … 1つ目（例: AI_rechain）
    ・SLACK_BOT_TOKEN_2 / SLACK_CHANNEL_2       … 2つ目（例: rechain-inc）
    片方だけ設定されている組は無視する（両方揃って初めて有効）。
    """
    targets = []
    for label, tok_env, ch_env in [
        ("primary", "SLACK_BOT_TOKEN", "SLACK_CHANNEL"),
        ("secondary", "SLACK_BOT_TOKEN_2", "SLACK_CHANNEL_2"),
    ]:
        token = os.environ.get(tok_env, "").strip()
        channel = os.environ.get(ch_env, "").strip()
        if token and channel:
            targets.append({"label": label, "token": token, "channel": channel})
    return targets

DATA_DIR = os.environ.get("BOOK_DATA_DIR", os.path.join(BOT_DIR, "data")).strip()
SUBDIRS = [
    s.strip()
    for s in os.environ.get("BOOK_SUBDIRS", "Books,02_読書メモ").split(",")
    if s.strip()
]


def die(msg):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def list_notes():
    notes = []
    for sub in SUBDIRS:
        d = os.path.join(DATA_DIR, sub)
        if os.path.isdir(d):
            notes += [
                os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md")
            ]
    return notes


def parse_note(path):
    """Books / 読書メモ どちらのスキーマにも対応して情報を取り出す。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()

    fm = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            km = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
            if km:
                key, val = km.group(1), km.group(2).strip()
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                fm[key] = val

    desc = ""
    dm = re.search(
        r"<!--\s*(?:bookshelf|kindle)-description:start\s*-->(.*?)<!--\s*(?:bookshelf|kindle)-description:end\s*-->",
        text,
        re.DOTALL,
    )
    if dm:
        body = re.sub(r"^\s*#+\s*概要\s*$", "", dm.group(1), flags=re.MULTILINE)
        desc = body.strip()

    stem = os.path.splitext(os.path.basename(path))[0]
    title = fm.get("title") or fm.get("kindle-title") or stem
    author = fm.get("author") or fm.get("kindle-author", "")
    publisher = fm.get("publisher", "")
    publish_date = fm.get("publishDate", "")

    # 表紙: ローカルの webp（Books）優先、無ければ公開URL（Kindleの imageUrl）
    local_cover = ""
    cov = fm.get("cover", "")
    if cov:
        p = os.path.join(DATA_DIR, cov)
        if os.path.exists(p):
            local_cover = p
    remote_cover = fm.get("imageUrl") or fm.get("kindle-bookImageUrl", "")

    return {
        "title": title,
        "author": author,
        "publisher": publisher,
        "publish_date": publish_date,
        "desc": desc,
        "local_cover": local_cover,
        "remote_cover": remote_cover,
    }


def choose_book():
    notes = list_notes()
    if not notes:
        die(f"本データが見つかりません: {DATA_DIR} / {SUBDIRS}")

    posted = set()
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            posted = {line.strip() for line in f if line.strip()}

    rel = {p: os.path.relpath(p, DATA_DIR) for p in notes}
    candidates = [p for p in notes if rel[p] not in posted]
    if not candidates:
        candidates = notes
        open(HISTORY_FILE, "w").close()

    chosen = random.choice(candidates)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(rel[chosen] + "\n")
    return chosen


def webp_to_png(src):
    out = os.path.join(tempfile.gettempdir(), f"bookcover_{uuid.uuid4().hex}.png")
    if shutil.which("sips"):  # macOS
        try:
            subprocess.run(
                ["sips", "-s", "format", "png", src, "--out", out],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return out if os.path.exists(out) else ""
        except Exception as e:
            print(f"[warn] sips変換失敗、Pillowを試します: {e}", file=sys.stderr)
    try:
        from PIL import Image

        Image.open(src).convert("RGB").save(out, "PNG")
        return out
    except Exception as e:
        print(f"[warn] 表紙のpng変換に失敗: {e}", file=sys.stderr)
        return ""


def generate_comment(title, author, desc):
    prompt = (
        "あなたは社内Slackで毎朝1冊の本を紹介する、本好きの同僚です。\n"
        "以下の本について、読みたくなるような紹介コメントを日本語で2〜3文で書いてください。\n"
        "・カジュアルで親しみやすい口調（絵文字は1個まで）\n"
        "・概要の丸写しではなく、その本の面白さ・読む価値が伝わるように\n"
        "・前置きや「はい」などは不要。コメント本文だけを返す\n\n"
        f"タイトル: {title}\n"
        f"著者: {author}\n"
        f"概要: {desc or '（概要情報なし）'}\n"
    )
    body = json.dumps(
        {"model": MODEL, "max_tokens": 512, "messages": [{"role": "user", "content": prompt}]}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.load(resp)
    except urllib.error.HTTPError as e:
        die(f"Anthropic API エラー {e.code}: {e.read().decode('utf-8', 'replace')}")
    except Exception as e:
        die(f"Anthropic API 呼び出しに失敗: {e}")
    for block in result.get("content", []):
        if block.get("type") == "text":
            return block["text"].strip()
    die("Anthropic API から本文が取れませんでした")


def build_text(b, comment):
    meta = " ".join(x for x in [b["author"], b["publisher"], b["publish_date"]] if x)
    parts = ["📚 *今日の一冊*", "", f"*{b['title']}*"]
    if meta:
        parts.append(meta)
    parts += ["", comment]
    if b["desc"]:
        short = b["desc"] if len(b["desc"]) <= 280 else b["desc"][:279] + "…"
        parts += ["", f"📖 {short}"]
    return "\n".join(parts)


def build_plain_text(b, comment):
    meta = " ".join(x for x in [b["author"], b["publisher"], b["publish_date"]] if x)
    parts = ["今日の一冊", "", b["title"]]
    if meta:
        parts.append(meta)
    parts += ["", comment]
    if b["desc"]:
        short = b["desc"] if len(b["desc"]) <= 280 else b["desc"][:279] + "..."
        parts += ["", f"概要: {short}"]
    if b["remote_cover"]:
        parts += ["", f"表紙: {b['remote_cover']}"]
    return "\n".join(parts)


def post_wxpusher(b, comment):
    app_token = os.environ.get("WXPUSHER_APP_TOKEN", "").strip()
    uids = parse_csv_env("WXPUSHER_UIDS")
    topic_ids = []
    for raw in parse_csv_env("WXPUSHER_TOPIC_IDS"):
        try:
            topic_ids.append(int(raw))
        except ValueError:
            die(f"WXPUSHER_TOPIC_IDS は数値のカンマ区切りで指定してください: {raw}")
    if not app_token:
        die("WXPUSHER_APP_TOKEN が未設定です")
    if not uids and not topic_ids:
        die("WXPUSHER_UIDS または WXPUSHER_TOPIC_IDS のどちらかが必要です")

    payload = {
        "appToken": app_token,
        "content": build_plain_text(b, comment),
        "summary": f"今日の一冊: {b['title']}"[:100],
        "contentType": 1,
        "uids": uids,
        "topicIds": topic_ids,
    }
    req = urllib.request.Request(
        "https://wxpusher.zjiecode.com/api/send/message",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        die(f"WxPusher API エラー {e.code}: {e.read().decode('utf-8', 'replace')}")
    except Exception as e:
        die(f"WxPusher API 呼び出しに失敗: {e}")
    if res.get("code") != 1000:
        die(f"WxPusher 送信失敗: {res}")
    data = res.get("data")
    # data は各宛先への配信結果。公開リポジトリのため uid はログに出さず code/status のみ表示。
    if isinstance(data, list):
        summary = [{"code": d.get("code"), "status": d.get("status")} for d in data]
        print(f"[info] WxPusher応答: 宛先{len(data)}件 {json.dumps(summary, ensure_ascii=False)}")
        if len(data) == 0:
            die("WxPusher: 配信対象が0件です。UID が対象アプリ(appToken)を未購読/無効の可能性が高いです。"
                "WxPusher管理画面で当該UIDの購読状態と appToken との対応を確認してください")
    else:
        print(f"[info] WxPusher応答(data): {json.dumps(data, ensure_ascii=False)}")
    print("[info] WeChat(WxPusher) へ投稿しました")


def post_serverchan(b, comment):
    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()
    if not sendkey:
        die("SERVERCHAN_SENDKEY が未設定です")

    data = urllib.parse.urlencode(
        {
            "title": f"今日の一冊: {b['title']}",
            "desp": build_plain_text(b, comment),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://sctapi.ftqq.com/{urllib.parse.quote(sendkey)}.send",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        die(f"ServerChan API エラー {e.code}: {e.read().decode('utf-8', 'replace')}")
    except Exception as e:
        die(f"ServerChan API 呼び出しに失敗: {e}")
    if res.get("code") not in (0, 200):
        die(f"ServerChan 送信失敗: {res}")
    print("[info] WeChat(ServerChan) へ投稿しました")


def post_to_wechat(b, comment):
    provider = os.environ.get("WECHAT_PROVIDER", "wxpusher").strip().lower()
    if provider == "wxpusher":
        post_wxpusher(b, comment)
    elif provider == "serverchan":
        post_serverchan(b, comment)
    else:
        die(f"未対応の WECHAT_PROVIDER です: {provider}")


def slack_api(method, payload, token):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        die(f"Slack API {method} 失敗: {res.get('error')}")
    return res


def post_text_with_image_url(b, comment, image_url, token, channel):
    meta = " ".join(x for x in [b["author"], b["publisher"], b["publish_date"]] if x)
    intro = f"*{b['title']}*" + (f"\n{meta}" if meta else "")
    section = {"type": "section", "text": {"type": "mrkdwn", "text": intro}}
    if image_url:
        section["accessory"] = {"type": "image", "image_url": image_url, "alt_text": b["title"]}
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📚 今日の一冊", "emoji": True}},
        section,
        {"type": "section", "text": {"type": "mrkdwn", "text": comment}},
    ]
    if b["desc"]:
        short = b["desc"] if len(b["desc"]) <= 280 else b["desc"][:279] + "…"
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"📖 {short}"}]})
    slack_api(
        "chat.postMessage",
        {"channel": channel, "text": f"📚 今日の一冊: {b['title']}", "blocks": blocks},
        token,
    )


def upload_local_cover(b, comment, png_path, token, channel):
    text = build_text(b, comment)
    length = os.path.getsize(png_path)
    data = urllib.parse.urlencode({"filename": f"{b['title']}.png", "length": length}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/files.getUploadURLExternal",
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        die(f"Slack files.getUploadURLExternal 失敗: {res.get('error')}")
    upload_url, file_id = res["upload_url"], res["file_id"]

    with open(png_path, "rb") as f:
        content = f.read()
    boundary = "----bookslack" + uuid.uuid4().hex
    payload = b"".join([
        ("--" + boundary + "\r\n").encode(),
        b'Content-Disposition: form-data; name="file"; filename="cover.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        content,
        b"\r\n",
        ("--" + boundary + "--\r\n").encode(),
    ])
    req = urllib.request.Request(
        upload_url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=60).read()

    slack_api(
        "files.completeUploadExternal",
        {
            "files": [{"id": file_id, "title": b["title"]}],
            "channel_id": channel,
            "initial_comment": text,
        },
        token,
    )


def post_to_target(b, comment, png, target):
    """1つのワークスペースへ投稿する。png はローカル表紙の変換結果（無ければ ""）。"""
    token, channel, label = target["token"], target["channel"], target["label"]
    if png:
        print(f"[info] [{label}] ローカル表紙をアップロードします")
        upload_local_cover(b, comment, png, token, channel)
    elif b["remote_cover"]:
        print(f"[info] [{label}] 公開URLの表紙で投稿します")
        post_text_with_image_url(b, comment, b["remote_cover"], token, channel)
    else:
        print(f"[info] [{label}] 表紙なしでテキスト投稿します")
        post_text_with_image_url(b, comment, "", token, channel)
    print(f"[info] [{label}] Slack へ投稿しました")


def main():
    if not API_KEY:
        die("ANTHROPIC_API_KEY が未設定です")
    requested_targets = notify_targets()
    supported_targets = {"slack", "wechat"}
    unsupported_targets = requested_targets - supported_targets
    if unsupported_targets:
        die(f"未対応の NOTIFY_TARGETS です: {', '.join(sorted(unsupported_targets))}")

    slack_targets = collect_slack_targets() if "slack" in requested_targets else []
    if "slack" in requested_targets and not slack_targets:
        die("Slack投稿先が未設定です（SLACK_BOT_TOKEN / SLACK_CHANNEL の組が最低1つ必要）")
    if slack_targets:
        print(f"[info] Slack投稿先ワークスペース数: {len(slack_targets)}（{', '.join(t['label'] for t in slack_targets)}）")
    if "wechat" in requested_targets:
        print(f"[info] WeChat通知を有効化します（provider={os.environ.get('WECHAT_PROVIDER', 'wxpusher').strip().lower()}）")

    path = choose_book()
    b = parse_note(path)
    print(f"[info] 選ばれた本: {b['title']}（{os.path.basename(os.path.dirname(path))}）")

    comment = generate_comment(b["title"], b["author"], b["desc"])

    # 表紙の webp→png 変換は1回だけ。各ワークスペースへは同じpngを個別アップロード。
    png = ""
    if b["local_cover"]:
        png = webp_to_png(b["local_cover"])

    try:
        for target in slack_targets:
            post_to_target(b, comment, png, target)
        if "wechat" in requested_targets:
            post_to_wechat(b, comment)
    finally:
        if png:
            try:
                os.remove(png)
            except OSError:
                pass


if __name__ == "__main__":
    main()
