import unittest
from unittest.mock import patch

import quiz_post


class QuizAuthTests(unittest.TestCase):
    def test_invalid_auth_prevents_loading_and_posting(self):
        with patch.dict('os.environ', {'SLACK_BOT_TOKEN_2': 'fake', 'SLACK_CHANNEL_QUIZ': 'channel'}), patch.object(quiz_post, 'check_slack_auth', side_effect=RuntimeError('invalid_auth')) as auth, patch.object(quiz_post, 'load_quiz_bank') as bank, patch.object(quiz_post, 'slack_post') as post:
            with self.assertRaisesRegex(RuntimeError, 'invalid_auth'):
                quiz_post.main()
            auth.assert_called_once_with('fake', 'quiz/secondary')
            bank.assert_not_called()
            post.assert_not_called()
