#!/usr/bin/env python3
"""Report collection freshness and posting capacity without sending to Slack."""
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dlab_news_post import load_state
from dlab_news_stock import JST, MAX_AGE_DAYS, load_bank, timestamp


def assess(bank, state, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(JST).date()
    age = now - timestamp(bank['last_checked_at'])
    remaining = sum(a['dlab_url'] not in state['posted'] and
                    0 <= (today - date.fromisoformat(a['published'])).days <= MAX_AGE_DAYS
                    for a in bank['articles'])
    posted_today = state.get('last_posted_date') == today.isoformat()
    errors, warnings = [], []
    if age > timedelta(days=7):
        errors.append('Collection has not succeeded for over 7 days; refresh the stock.')
    elif age >= timedelta(days=3):
        warnings.append('Collection is at least 3 days old; check the daily collection task.')
    if state.get('pending_detail'):
        errors.append('A Slack thread reply is pending; inspect the posting step before retrying.')
    if remaining == 0:
        message = 'No fresh unposted articles remain; collect new articles before the next posting run.'
        (warnings if posted_today else errors).append(message)
    elif remaining < 3:
        warnings.append('Fewer than 3 fresh unposted articles remain.')
    summary = '\n'.join([
        '## DラボAIニュースの稼働状況',
        f'- 確認日（JST）: {today}',
        f'- 最終収集確認（JST）: {timestamp(bank["last_checked_at"]).astimezone(JST).isoformat()}',
        f'- 投稿可能な未投稿記事: {remaining}件',
        f'- 本日の親投稿記録: {"あり" if posted_today else "なし"}',
        f'- 未送信の詳細返信: {"あり" if state.get("pending_detail") else "なし"}',
        *[f'- ERROR: {message}' for message in errors],
        *[f'- WARNING: {message}' for message in warnings],
        '',
    ])
    return errors, warnings, summary


def main():
    errors, warnings, summary = assess(load_bank(), load_state())
    print(summary)
    for level, messages in [('error', errors), ('warning', warnings)]:
        for message in messages:
            print(f'::{level} title=Dlab news health::{message}')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as out:
            out.write(summary)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
