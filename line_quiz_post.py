#!/usr/bin/env python3
"""dlab記事ベースの「今日のクイズ」をLINE公式アカウントからBroadcast配信する。

LINEにはSlackのスレッド機能がないため、問題と正解を2回の別実行(phase)に分けて送る。

- phase=question: 未投稿の記事を1つ選び、問題文(4問+心理学ボーナス1問)をBroadcast。
  選んだ day_index を line_quiz_state.json に「回答待ち」として記録する。
  すでに回答待ちがある場合は何もしない(前回の正解がまだ送られていない)。
- phase=answer: line_quiz_state.json に記録された day_index の正解・解説をBroadcast。
  送信後、その day_index を line_quiz_posted.log に記録し、state をクリアする。
  回答待ちが無ければ何もしない。

全記事を投稿し終えたら line_quiz_posted.log をリセットして最初から繰り返す
(quiz_post.py / post_book.py と同じ仕組み)。
"""
import json
import os
import sys
import urllib.request

import openpyxl

QUIZ_BANK_PATH = "data/quiz/quiz_bank.xlsx"
POSTED_LOG_PATH = "line_quiz_posted.log"
STATE_PATH = "line_quiz_state.json"

LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


def load_quiz_bank():
    wb = openpyxl.load_workbook(QUIZ_BANK_PATH, read_only=True)

    ws = wb["quiz_bank"]
    articles = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        (day_index, channel, channel_label, title, url, published, q_no,
         question, choice_a, choice_b, choice_c, choice_d, correct,
         explanation) = row
        article = articles.setdefault(day_index, {
            "day_index": day_index,
            "channel_label": channel_label,
            "title": title,
            "url": url,
            "published": published,
            "questions": [],
        })
        article["questions"].append({
            "q_no": q_no,
            "question": question,
            "choices": {"A": choice_a, "B": choice_b, "C": choice_c, "D": choice_d},
            "correct": correct,
            "explanation": explanation,
        })

    ws2 = wb["psychology_bonus"]
    bonus_by_day = {}
    for row in ws2.iter_rows(min_row=2, values_only=True):
        (day_index, title, url, published, question, choice_a, choice_b,
         choice_c, choice_d, correct, explanation) = row
        bonus_by_day[day_index] = {
            "title": title,
            "url": url,
            "published": published,
            "question": question,
            "choices": {"A": choice_a, "B": choice_b, "C": choice_c, "D": choice_d},
            "correct": correct,
            "explanation": explanation,
        }

    for day_index, article in articles.items():
        article["psychology_bonus"] = bonus_by_day.get(day_index)

    return {a["day_index"]: a for a in articles.values()}


def load_posted_days():
    if not os.path.exists(POSTED_LOG_PATH):
        return set()
    with open(POSTED_LOG_PATH, encoding="utf-8") as f:
        return {int(line.strip()) for line in f if line.strip()}


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("pending_day_index")


def save_state(day_index):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"pending_day_index": day_index}, f)


def clear_state():
    if os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)


def pick_next_article(articles_by_day, posted_days, offset=0):
    """未投稿の記事を1つ選ぶ。offsetを指定すると、ローテーションの開始位置を
    ずらせる（Slack版と同じ記事バンクを使いつつ、出す記事をずらして被らないようにするため）。
    """
    days = sorted(articles_by_day)
    n = len(days)
    for i in range(n):
        day_index = days[(offset + i) % n]
        if day_index not in posted_days:
            return articles_by_day[day_index]
    return None


def build_quiz_message(article):
    lines = [f"🧠 今日のクイズ（テーマ: {article['channel_label']}）", ""]
    lines.append(f"元記事: {article['title']}（{article['published']}時点の情報）")
    lines.append(article["url"])
    lines.append("")
    for q in article["questions"]:
        lines.append(f"Q{q['q_no']}. {q['question']}")
        lines.append(
            f"A) {q['choices']['A']}\nB) {q['choices']['B']}\n"
            f"C) {q['choices']['C']}\nD) {q['choices']['D']}"
        )
        lines.append("")

    bonus = article.get("psychology_bonus")
    if bonus:
        lines.append("🧩 心理学ボーナス問題")
        lines.append(f"出典: {bonus['title']}（{bonus['published']}時点の情報）")
        lines.append(bonus["url"])
        lines.append(f"Q5. {bonus['question']}")
        lines.append(
            f"A) {bonus['choices']['A']}\nB) {bonus['choices']['B']}\n"
            f"C) {bonus['choices']['C']}\nD) {bonus['choices']['D']}"
        )
        lines.append("")

    lines.append("正解は2時間後にお届けします👇")
    return "\n".join(lines).strip()


def build_answer_message(article):
    lines = ["✅ 正解発表", ""]
    for q in article["questions"]:
        lines.append(f"Q{q['q_no']}: {q['correct']} ({q['choices'][q['correct']]})")
        lines.append(f"　→ {q['explanation']}")

    bonus = article.get("psychology_bonus")
    if bonus:
        lines.append(f"Q5(心理学ボーナス): {bonus['correct']} ({bonus['choices'][bonus['correct']]})")
        lines.append(f"　→ {bonus['explanation']}")

    return "\n".join(lines)


def line_broadcast(token, text):
    payload = {"messages": [{"type": "text", "text": text}]}
    req = urllib.request.Request(
        LINE_BROADCAST_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LINE API error: {e.code} {e.read().decode('utf-8')}")


def main():
    phase = os.environ.get("QUIZ_PHASE", "question")
    if len(sys.argv) > 1:
        phase = sys.argv[1]

    token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
    articles_by_day = load_quiz_bank()
    # Slack版(quiz_post.py)と同じ記事バンクを使うが、同じ日に同じ問題を出さないよう
    # ローテーションを半周ずらす（Slackはday_index=1から、LINEはその半周先から開始）。
    offset = len(articles_by_day) // 2

    if phase == "question":
        pending = load_state()
        if pending is not None:
            print(f"skip: day_index={pending} の正解がまだ送信されていません")
            return

        posted_days = load_posted_days()
        article = pick_next_article(articles_by_day, posted_days, offset=offset)
        if article is None:
            # 全部投稿し終えたのでリセットして最初の記事から再開する
            posted_days = set()
            with open(POSTED_LOG_PATH, "w", encoding="utf-8") as f:
                f.write("")
            article = pick_next_article(articles_by_day, posted_days, offset=offset)

        line_broadcast(token, build_quiz_message(article))
        save_state(article["day_index"])
        print(f"posted question day_index={article['day_index']} title={article['title']}")

    elif phase == "answer":
        pending = load_state()
        if pending is None:
            print("skip: 回答待ちの記事がありません")
            return

        article = articles_by_day[pending]
        line_broadcast(token, build_answer_message(article))

        posted_days = load_posted_days()
        posted_days.add(article["day_index"])
        with open(POSTED_LOG_PATH, "w", encoding="utf-8") as f:
            for day in sorted(posted_days):
                f.write(f"{day}\n")
        clear_state()
        print(f"posted answer day_index={article['day_index']} title={article['title']}")

    else:
        raise ValueError(f"unknown phase: {phase}")


if __name__ == "__main__":
    main()
