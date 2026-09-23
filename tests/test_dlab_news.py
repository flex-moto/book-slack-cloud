import copy
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dlab_news_post import build_message, pick_next_article, post_news
from dlab_news_stock import load_bank, merge_articles, validate_article

NOW = datetime(2026, 9, 23, 14, 0, tzinfo=timezone.utc)


def article(day='2026-09-18', slug='new'):
    return dict(title='AI記事', url='https://example.com/news',
                dlab_url=f'https://daigovideolab.jp/blog/{slug}', published=day,
                collected_at='2026-09-23T12:00:00+00:00', summary='概要', detail='詳細')


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.bank = dict(schema_version=1, last_checked_at=NOW.isoformat(), articles=[article()])
        self.state = dict(schema_version=1, posted={}, last_posted_date=None, pending_detail=None)

    def test_newest_first_then_remaining(self):
        older, newer = article('2026-09-16', 'old'), article()
        self.assertEqual(pick_next_article([older, newer], {}, NOW.date()), newer)
        self.assertEqual(pick_next_article([older, newer], {newer['dlab_url']}, NOW.date()), older)

    def test_expired_future_and_exhausted_never_recycle(self):
        self.assertIsNone(pick_next_article([article('2026-09-08')], {}, NOW.date()))
        self.assertIsNone(pick_next_article([article('2026-09-24')], {}, NOW.date()))
        self.assertIsNone(pick_next_article([article()], {article()['dlab_url']}, NOW.date()))
        self.assertIsNone(pick_next_article([], {}, NOW.date()))

    def test_age_boundary(self):
        self.assertIsNotNone(pick_next_article([article('2026-09-09')], {}, NOW.date()))

    def test_merge_deduplicates_and_keeps_original_dates(self):
        updated = article('2026-09-23')
        updated['dlab_url'] += '/?utm_source=test'
        updated['collected_at'] = NOW.isoformat()
        result, added = merge_articles(self.bank, [updated, updated], NOW)
        self.assertEqual(added, 0)
        self.assertEqual(len(result['articles']), 1)
        self.assertEqual(result['articles'][0]['published'], '2026-09-18')
        self.assertEqual(result['articles'][0]['collected_at'], article()['collected_at'])
        self.assertEqual(self.bank['articles'][0], article())

    def test_empty_refresh_retains_stock(self):
        result, added = merge_articles(self.bank, [], NOW)
        self.assertEqual(added, 0)
        self.assertEqual(result['articles'], self.bank['articles'])

    def test_bad_source_and_dates_rejected(self):
        for key, value in [('published', '2026-09-24'), ('dlab_url', 'https://evil.example/blog/a'),
                           ('url', 'javascript:alert(1)'), ('collected_at', '2026-09-23T12:00:00'),
                           ('summary', '')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_article(dict(article(), **{key: value}), NOW)

    def test_dry_run_never_posts_or_saves(self):
        with patch('dlab_news_post.slack_post') as slack, patch('dlab_news_post.save_json') as save:
            post_news(self.bank, self.state, dry_run=True, now=NOW)
            slack.assert_not_called()
            save.assert_not_called()
        self.assertEqual(self.state['posted'], {})

    def test_success_and_same_day_repeat(self):
        with tempfile.TemporaryDirectory() as tmp, patch('dlab_news_post.slack_post', return_value={'ts': '1'}) as slack:
            path = Path(tmp) / 'state.json'
            post_news(self.bank, self.state, 'token', 'channel', now=NOW, state_path=path)
            saved = json.loads(path.read_text())
            self.assertIsNone(saved['pending_detail'])
            self.assertIn(article()['dlab_url'], saved['posted'])
            post_news(self.bank, saved, 'token', 'channel', now=NOW, state_path=path)
            self.assertEqual(slack.call_count, 2)

    def test_reply_failure_resumes_without_second_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            with patch('dlab_news_post.slack_post', side_effect=[{'ts': '123'}, RuntimeError('failure')]):
                with self.assertRaises(RuntimeError):
                    post_news(self.bank, self.state, 'token', 'channel', now=NOW, state_path=path)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['pending_detail']['ts'], '123')
            with patch('dlab_news_post.slack_post', return_value={'ts': '124'}) as slack:
                post_news(self.bank, saved, 'token', 'channel', now=NOW, state_path=path)
                slack.assert_called_once()
                self.assertEqual(slack.call_args.kwargs['thread_ts'], '123')
            self.assertIsNone(json.loads(path.read_text())['pending_detail'])

    def test_stale_collection_fails_before_posting(self):
        self.bank['last_checked_at'] = '2026-09-08T00:00:00Z'
        with patch('dlab_news_post.slack_post') as slack, self.assertRaises(RuntimeError):
            post_news(self.bank, self.state, now=NOW)
        slack.assert_not_called()

    def test_empty_stock_does_not_change_history(self):
        self.bank['articles'] = []
        before = copy.deepcopy(self.state)
        with patch('dlab_news_post.slack_post') as slack:
            post_news(self.bank, self.state, now=NOW)
        slack.assert_not_called()
        self.assertEqual(self.state, before)

    def test_dates_and_slack_mentions(self):
        message = build_message(dict(article(), summary='<!channel> & <hello>'))
        self.assertIn('記事公開日：2026-09-18 ／ 収集日：2026-09-23', message)
        self.assertNotIn('<!channel>', message)

    def test_real_stock_validates(self):
        bank = load_bank()
        self.assertGreaterEqual(len(bank['articles']), 2)


if __name__ == '__main__':
    unittest.main()
