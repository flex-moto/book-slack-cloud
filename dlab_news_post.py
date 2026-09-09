#!/usr/bin/env python3
"""dlab(daigovideolab.jp)のAI関連記事を1日1本、Slackに紹介投稿する。

data/dlab_news/news_bank.xlsx の news_bank シートから、まだ投稿していない
day_index の記事を1件選んで投稿する。全件投稿し終えたら dlab_news_posted.log
をリセットして最初から繰り返す。
"""
import json
import os
import urllib.request

import openpyxl

NEWS_BANK_PATH = "data/dlab_news/news_bank.xlsx"
POSTED_LOG_PATH = "dlab_news_posted.log"

SLACK_API_URL = "https://slack.com/api/chat.postMessage"


def load_news_bank():
    wb = openpyxl.load_workbook(NEWS_BANK_PATH, read_only=True)
    ws = wb["news_bank"]
    articles = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        day_index, title, url, published, summary = row
        if day_index is None:
            continue
        articles.append({
            "day_index": day_index,
            "title": title,
            "url": url,
            "published": published,
            "summary": summary,
        })
    return sorted(articles, key=lambda a: a["day_index"])


def load_posted_days():
    if not os.path.exists(POSTED_LOG_PATH):
        return set()
    with open(POSTED_LOG_PATH, encoding="utf-8") as f:
        return {int(line.strip()) for line in f if line.strip()}


def pick_next_article(articles, posted_days):
    for article in articles:
        if article["day_index"] not in posted_days:
            return article
    return None


def build_message(article):
    lines = [
        "🤖 *今日のdlab AI情報*",
        "",
        f"*<{article['url']}|{article['title']}>*（{article['published']}時点の情報）",
        "",
        article["summary"],
    ]
    return "\n".join(lines)


def slack_post(token, channel, text):
    payload = {"channel": channel, "text": text}
    req = urllib.request.Request(
        SLACK_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(f"Slack API error: {result}")
    return result


def main():
    token = os.environ["SLACK_BOT_TOKEN_2"]
    channel = os.environ.get("SLACK_CHANNEL_DLAB_NEWS", "C05KPV4DSLS")

    articles = load_news_bank()
    posted_days = load_posted_days()
    article = pick_next_article(articles, posted_days)

    if article is None:
        posted_days = set()
        article = articles[0]

    text = build_message(article)
    slack_post(token, channel, text)

    posted_days.add(article["day_index"])
    with open(POSTED_LOG_PATH, "w", encoding="utf-8") as f:
        for day in sorted(posted_days):
            f.write(f"{day}\n")

    print(f"posted day_index={article['day_index']} title={article['title']}")


if __name__ == "__main__":
    main()
