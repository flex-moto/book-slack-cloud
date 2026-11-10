"""Metadata regressions; all external calls are mocked."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import post_book


ROOT = Path(post_book.__file__).parent
SAP_NOTE = ROOT / 'data/02_読書メモ/初めてSAP導入に取り組む方に贈る SAP導入PJ 初心者が知っておくべきこと、独学で1人前になる方法- Soloblog.md'
SAP_TITLE = (
    '初めてSAP導入に取り組む方に贈る SAP導入PJ 初心者が知っておくべきこと、独学で1人前になる方法 : '
    '～プロジェクト計画、要件定義、設計、開発、テストまで～'
)


class MetadataTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ファイル名の書名.md'
            path.write_text(text, encoding='utf-8')
            return post_book.parse_note(path)

    def test_september_18_title_reaches_ai_and_slack(self):
        book = post_book.parse_note(SAP_NOTE)
        self.assertEqual(book['title'], SAP_TITLE)
        self.assertEqual(book['author'], 'Soloblog')
        self.assertEqual(book['desc'], '')
        self.assertEqual(book['remote_cover'], 'https://m.media-amazon.com/images/I/71MeWFss+PL._SX1024.jpg')
        with patch('post_book.urllib.request.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = json.dumps({
                'content': [{'type': 'text', 'text': '紹介コメント'}]
            }).encode()
            comment = post_book.generate_comment(book['title'], book['author'], book['desc'])
        prompt = json.loads(request.call_args.args[0].data)['messages'][0]['content']
        self.assertIn('タイトル: ' + SAP_TITLE, prompt)
        self.assertIn('概要: （概要情報なし）', prompt)
        with patch('post_book.slack_api') as slack:
            post_book.post_text_with_image_url(book, comment, book['remote_cover'], 'fake', 'fake')
        payload = slack.call_args.args[1]
        self.assertEqual(payload['text'], '📚 今日の一冊: ' + SAP_TITLE)
        self.assertEqual(payload['blocks'][1]['text']['text'], '*' + SAP_TITLE + '*\nSoloblog')
        self.assertEqual(payload['blocks'][1]['accessory']['alt_text'], SAP_TITLE)

    def test_yaml_block_styles(self):
        for style in ('>', '>-', '>+', '|', '|-', '|+', '>2-', '|2-'):
            with self.subTest(style=style):
                book = self.parse(f'---\nkindle-title: {style}\n  第一部\n  第二部\n---\n')
                self.assertEqual(book['title'], '第一部 第二部')

    def test_quotes_comments_and_dates(self):
        book = self.parse('---\ntitle: "SAP: 入門 #1" # metadata\nauthor: \'O\'\'Brien\'\npublishDate: 2026-09-18\n---\n')
        self.assertEqual(book['title'], 'SAP: 入門 #1')
        self.assertEqual(book['author'], "O'Brien")
        self.assertEqual(book['publish_date'], '2026-09-18')
        self.assertIn('2026-09-18', post_book.build_text(book, '紹介'))

    def test_null_empty_and_non_scalar_titles_fall_back(self):
        for value in ('null', '~', '', '""', '"   "', '[]', '{}', 'false', '\">-\"'):
            with self.subTest(value=value):
                book = self.parse(f'---\ntitle: {value}\nkindle-title: null\nauthor: null\n---\n')
                self.assertEqual(book['title'], 'ファイル名の書名')
                self.assertEqual(book['author'], '')
        book = self.parse('---\ntitle: null\nkindle-title: Kindleの書名\nauthor: null\nkindle-author: 著者\n---\n')
        self.assertEqual(book['title'], 'Kindleの書名')
        self.assertEqual(book['author'], '著者')

    def test_bom_crlf_and_frontmatter_at_eof(self):
        book = self.parse('\ufeff---\r\nkindle-title: >-\r\n  日本語タイトル\r\n---')
        self.assertEqual(book['title'], '日本語タイトル')

    def test_no_frontmatter(self):
        self.assertEqual(self.parse('# 本文のみ')['title'], 'ファイル名の書名')

    def test_bad_yaml_fails_before_generation(self):
        for fm in ('title: [', '- item', '!!python/object/apply:os.system ["echo unsafe"]'):
            with self.subTest(fm=fm), self.assertRaises(ValueError):
                self.parse('---\n' + fm + '\n---\n')

    def test_cover_and_description_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'cover.webp').touch()
            with patch.object(post_book, 'DATA_DIR', directory):
                book = self.parse('---\ntitle: 書名\ncover: cover.webp\n---\n<!-- bookshelf-description:start -->\n## 概要\n本の概要。\n<!-- bookshelf-description:end -->')
            self.assertEqual(book['local_cover'], str(Path(directory) / 'cover.webp'))
            self.assertEqual(book['desc'], '本の概要。')

    def test_every_bundled_book_can_be_rendered(self):
        notes = sorted((ROOT / 'data/Books').glob('*.md')) + sorted((ROOT / 'data/02_読書メモ').glob('*.md'))
        self.assertTrue(notes)
        for path in notes:
            with self.subTest(note=path.name):
                book = post_book.parse_note(path)
                self.assertTrue(book['title'].strip())
                self.assertNotIn(book['title'].lower(), {'null', 'none', '>-', '|', '-'})
                self.assertTrue(all(isinstance(value, str) for value in book.values()))
                self.assertIn(book['title'], post_book.build_text(book, '紹介'))
                self.assertIn(book['title'], post_book.build_plain_text(book, '紹介'))
                with patch('post_book.slack_api') as slack:
                    post_book.post_text_with_image_url(book, '紹介', book['remote_cover'], 'fake', 'fake')
                self.assertIn(book['title'], slack.call_args.args[1]['text'])


class DeliveryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.state_path = root / 'state.json'
        self.history_path = root / 'posted.log'
        self.targets = [
            {'label': 'primary', 'token': 'fake-one', 'channel': 'C1'},
            {'label': 'secondary', 'token': 'fake-two', 'channel': 'C2'},
        ]
        self.book = {'title': 'Test', 'author': '', 'desc': '', 'local_cover': '', 'remote_cover': ''}
        for name, value in [('STATE_FILE', str(self.state_path)), ('HISTORY_FILE', str(self.history_path)), ('API_KEY', 'fake')]:
            patcher = patch.object(post_book, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in [('notify_targets', {'slack', 'wechat'}), ('collect_slack_targets', self.targets),
                            ('choose_book', str(Path(post_book.DATA_DIR) / 'Books/test.md')),
                            ('parse_note', self.book), ('generate_comment', 'saved comment')]:
            patcher = patch.object(post_book, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_secondary_failure_resumes_only_missing_targets(self):
        with patch('post_book.check_slack_auth'), patch('post_book.post_to_target', side_effect=[None, SystemExit(1)]), patch('post_book.post_to_wechat') as wechat:
            with self.assertRaises(SystemExit):
                post_book.main()
            wechat.assert_not_called()
        self.assertEqual(json.loads(self.state_path.read_text())['sent'], ['primary'])
        self.assertFalse(self.history_path.exists())
        with patch('post_book.check_slack_auth') as auth, patch('post_book.post_to_target') as send, patch('post_book.post_to_wechat') as wechat:
            post_book.main()
            auth.assert_called_once_with('fake-two', 'book/secondary')
            self.assertEqual(send.call_args.args[-1]['label'], 'secondary')
            send.assert_called_once()
            wechat.assert_called_once()
        self.choose_book.assert_called_once()
        self.generate_comment.assert_called_once()
        self.assertTrue(json.loads(self.state_path.read_text())['complete'])
        self.assertEqual(self.history_path.read_text(), 'Books/test.md\n')
        with patch('post_book.check_slack_auth') as auth, patch('post_book.post_to_target') as send:
            post_book.main()
            auth.assert_not_called()
            send.assert_not_called()

    def test_invalid_auth_stops_before_selection_or_generation(self):
        with patch('post_book.check_slack_auth', side_effect=RuntimeError('invalid_auth')), patch('post_book.post_to_target') as send:
            with self.assertRaises(RuntimeError):
                post_book.main()
            send.assert_not_called()
        self.choose_book.assert_not_called()
        self.generate_comment.assert_not_called()
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.history_path.exists())

    def test_wechat_failure_keeps_both_slack_successes(self):
        with patch('post_book.check_slack_auth'), patch('post_book.post_to_target'), patch('post_book.post_to_wechat', side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                post_book.main()
        with patch('post_book.check_slack_auth') as auth, patch('post_book.post_to_target') as send, patch('post_book.post_to_wechat') as wechat:
            post_book.main()
            auth.assert_not_called()
            send.assert_not_called()
            wechat.assert_called_once()

    def test_changed_pending_channel_blocks_delivery(self):
        with patch('post_book.check_slack_auth'), patch('post_book.post_to_target', side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                post_book.main()
        self.targets[0]['channel'] = 'DIFFERENT'
        with patch('post_book.check_slack_auth') as auth:
            with self.assertRaises(SystemExit):
                post_book.main()
            auth.assert_not_called()


if __name__ == '__main__':
    unittest.main()
