#!/usr/bin/env python3
"""Post one fresh, unposted article from the recurring dlab news stock."""
import argparse
import html
import json
import os
import random
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dlab_news_stock import BANK_PATH, JST, MAX_AGE_DAYS, ROOT, load_bank, save_json, timestamp

STATE_PATH = ROOT / 'data/dlab_news/post_state.json'
SLACK_API_URL = 'https://slack.com/api/chat.postMessage'


def load_state(path=STATE_PATH):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def pick_next_article(articles, posted_urls, today=None):
    today = today or datetime.now(JST).date()
    candidates = [a for a in articles if a['dlab_url'] not in posted_urls
                  and 0 <= (today - date.fromisoformat(a['published'])).days <= MAX_AGE_DAYS]
    if not candidates:
        return None
    newest = max(a['published'] for a in candidates)
    return random.choice([a for a in candidates if a['published'] == newest])


def escape(value):
    return html.escape(value, quote=False)


def build_message(article):
    title = escape(article['title']).replace('|', '｜')
    return '\n'.join([
        '🤖 *今日のdlab AI情報*', '',
        f"<{article['url']}|{title}>",
        f"記事公開日：{article['published']} ／ 収集日：{timestamp(article['collected_at']).astimezone(JST).date()}",
        '', escape(article['summary']), '', '詳しい内容はこのスレッドの返信をチェック👇',
    ])


def build_detail_message(article):
    return '\n'.join([
        '📖 *詳細*', '', escape(article['detail']), '',
        f"Dラボ記事：<{article['dlab_url']}|記事を読む>",
        f"参照元：<{article['url']}|元の情報を確認>",
    ])


def slack_post(token, channel, text, thread_ts=None):
    payload = {'channel': channel, 'text': text, 'link_names': False}
    if thread_ts:
        payload['thread_ts'] = thread_ts
    req = urllib.request.Request(
        SLACK_API_URL, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=utf-8'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    if not result.get('ok'):
        raise RuntimeError(f"Slack API error: {result.get('error', 'unknown')}")
    return result


def post_news(bank, state, token=None, channel=None, dry_run=False, now=None, state_path=STATE_PATH):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(JST).date()
    pending = state.get('pending_detail')
    if pending:
        if dry_run:
            print('Pending thread reply; will resume before selecting another article')
            return
        slack_post(token, pending['channel'], pending['text'], thread_ts=pending['ts'])
        state['pending_detail'] = None
        save_json(state_path, state)
        print('Resumed pending thread reply')
        return
    if state.get('last_posted_date') == today.isoformat():
        print('Already posted today; skipped')
        return
    if now - timestamp(bank['last_checked_at']) > timedelta(days=7):
        raise RuntimeError('News collection has not succeeded for 7 days; refresh stock before posting')
    article = pick_next_article(bank['articles'], state['posted'], today)
    if article is None:
        print('No fresh unposted articles; skipped (history retained)')
        return
    if dry_run:
        print(build_message(article))
        print(build_detail_message(article))
        return
    result = slack_post(token, channel, build_message(article))
    state['posted'][article['dlab_url']] = {'posted_at': now.isoformat(), 'ts': result['ts']}
    state['last_posted_date'] = today.isoformat()
    state['pending_detail'] = {'ts': result['ts'], 'channel': channel, 'text': build_detail_message(article)}
    # Save parent success even when the reply fails. The workflow persists on failure too.
    save_json(state_path, state)
    slack_post(token, channel, state['pending_detail']['text'], thread_ts=result['ts'])
    state['pending_detail'] = None
    save_json(state_path, state)
    print(f"posted url={article['dlab_url']} title={article['title']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    bank = load_bank(BANK_PATH)
    state = load_state()
    token = None if args.dry_run else os.environ['SLACK_BOT_TOKEN_2']
    channel = os.environ.get('SLACK_CHANNEL_DLAB_NEWS') or 'C05KPV4DSLS'
    post_news(bank, state, token, channel, args.dry_run)


if __name__ == '__main__':
    main()
