"""Exercise history persistence against a real, local bare Git remote."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parent / '.github/scripts/push-with-retry.sh'


class PersistenceTests(unittest.TestCase):
    def test_concurrent_unrelated_commit_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(where, *args):
                return subprocess.run(['git', '-C', str(where), *args], check=True,
                                      capture_output=True, text=True).stdout

            remote = root / 'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            first, second = root / 'first', root / 'second'
            git(root, 'clone', str(remote), str(first))
            git(first, 'checkout', '-b', 'master')
            git(first, 'config', 'user.name', 'Test')
            git(first, 'config', 'user.email', 'test@example.invalid')
            (first / 'posted.log').write_text('old\n')
            git(first, 'add', '.')
            git(first, 'commit', '-m', 'initial')
            git(first, 'push', 'origin', 'master')
            git(root, 'clone', str(remote), str(second))
            git(second, 'config', 'user.name', 'Test')
            git(second, 'config', 'user.email', 'test@example.invalid')
            (first / 'posted.log').write_text('old\nnew\n')
            git(first, 'commit', '-am', 'history')
            (second / 'sunrise_state.json').write_text('{}\n')
            git(second, 'add', '.')
            git(second, 'commit', '-m', 'concurrent monitor')
            git(second, 'push', 'origin', 'master')
            subprocess.run(['bash', str(SCRIPT)], cwd=first, check=True, capture_output=True,
                           env={**os.environ, 'GITHUB_REF_NAME': 'master'})
            self.assertEqual(git(remote, 'show', 'master:posted.log'), 'old\nnew\n')
            self.assertEqual(git(remote, 'show', 'master:sunrise_state.json'), '{}\n')


if __name__ == '__main__':
    unittest.main()
