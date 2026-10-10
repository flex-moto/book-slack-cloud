import copy
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from dlab_news_collect import CollectionError, collect, decode_rpc, parse_latest, summarize, target_content

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
URL = 'https://daigovideolab.jp/blog/new'
LATEST = f'## 最新ブログ記事\n\n1. [対象記事]({URL})\n   公開日: 2026-10-08\n   内容: 対象の概要'
CONTENT = f'1. [対象記事]({URL})\n公開日: 2026-10-08\n内容: 対象の内容 https://example.com/source\n\n2. [別の記事](https://daigovideolab.jp/blog/other)\n内容: 無関係な情報'


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.bank = {'schema_version': 1, 'last_checked_at': '2026-10-09T00:00:00Z', 'articles': []}

    def test_parse_latest_and_refuse_unknown_format(self):
        items = parse_latest(LATEST)
        self.assertEqual(items[0]['dlab_url'], URL)
        self.assertEqual(items[0]['published'], '2026-10-08')
        for text in ('', 'ログインしてください', '## 最新ブログ記事\n形式変更'):
            with self.assertRaises(CollectionError):
                parse_latest(text)

    def test_only_target_blocks_are_summarized(self):
        content = target_content(CONTENT, URL)
        self.assertIn('対象の内容', content)
        self.assertNotIn('無関係', content)
        with self.assertRaises(CollectionError):
            target_content(f'1. [別](https://daigovideolab.jp/blog/other)\n参照: {URL}', URL)

    def test_rpc_json_sse_and_error(self):
        response = {'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}}
        raw = json.dumps(response)
        self.assertEqual(decode_rpc(raw, 1), {'ok': True})
        self.assertEqual(decode_rpc('event: message\ndata: ' + raw + '\n\n', 1), {'ok': True})
        with self.assertRaises(CollectionError):
            decode_rpc(json.dumps({'id': 1, 'error': {'message': 'private'}}), 1)

    def test_failed_fetch_does_not_refresh_bank(self):
        before = copy.deepcopy(self.bank)
        client = Mock()
        client.call.side_effect = [LATEST, CollectionError('connection failed')]
        with self.assertRaises(CollectionError):
            collect(self.bank, client, 'key', 'model', NOW)
        self.assertEqual(self.bank, before)

    def test_known_articles_refresh_without_model_call(self):
        self.bank['articles'] = [{'dlab_url': URL, 'published': '2026-10-08'}]
        client = Mock()
        client.call.return_value = LATEST
        with patch('dlab_news_collect.summarize') as summary:
            result, added = collect(self.bank, client, '', 'model', NOW)
        summary.assert_not_called()
        self.assertEqual(added, 0)
        self.assertEqual(result['last_checked_at'], NOW.isoformat())

    def test_source_identity_and_dates_cannot_be_changed_by_model(self):
        output = {'summary': '短い概要', 'detail': '確認できた内容', 'source_url': 'https://invented.example/a', 'supported': True}
        response = {'content': [{'type': 'tool_use', 'name': 'save_summary', 'input': output}]}
        with patch('dlab_news_collect.post', return_value=(json.dumps(response), {})):
            result = summarize(parse_latest(LATEST)[0], CONTENT, 'key', 'model', NOW)
        self.assertEqual(result['url'], URL)
        self.assertEqual(result['published'], '2026-10-08')
        self.assertEqual(result['collected_at'], NOW.isoformat())

    def test_unsupported_summary_rejected(self):
        response = {'content': [{'type': 'tool_use', 'name': 'save_summary', 'input': {'supported': False}}]}
        with patch('dlab_news_collect.post', return_value=(json.dumps(response), {})), self.assertRaises(CollectionError):
            summarize(parse_latest(LATEST)[0], CONTENT, 'key', 'model', NOW)

    def test_new_article_merge_and_old_article_exclusion(self):
        client = Mock()
        client.call.side_effect = [LATEST, CONTENT]
        article = {'title': '対象', 'dlab_url': URL, 'url': URL, 'published': '2026-10-08',
                   'collected_at': NOW.isoformat(), 'summary': '概要', 'detail': '詳細'}
        with patch('dlab_news_collect.summarize', return_value=article):
            result, added = collect(self.bank, client, 'key', 'model', NOW)
        self.assertEqual(added, 1)
        self.assertEqual(result['articles'], [article])
        self.assertEqual(self.bank['articles'], [])
        client.call.side_effect = None
        client.call.return_value = LATEST.replace('2026-10-08', '2026-09-01')
        with patch('dlab_news_collect.summarize') as summary:
            result, added = collect(self.bank, client, 'key', 'model', NOW)
        summary.assert_not_called()
        self.assertEqual(added, 0)


if __name__ == '__main__':
    unittest.main()
