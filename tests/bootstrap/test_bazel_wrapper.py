"""The normal wrapper preserves Bazel defaults and explicit caller startup flags."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BazelWrapperTests(unittest.TestCase):
    def invoke(self, mode, *arguments):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / '.bazelversion').write_text('9.2.0\n')
            for name in ('bazel.sh', 'env.sh'):
                shutil.copyfile(ROOT / 'scripts' / name, root / 'scripts' / name)
            executable = root / 'fake-bazel'
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE"\n')
            executable.chmod(0o755)
            capture = root / 'arguments'
            env = dict(os.environ, RULES_MSBUILD_BAZEL=str(executable),
                       RULES_MSBUILD_BAZEL_MODE=mode, CAPTURE=str(capture))
            subprocess.run(['bash', str(root / 'scripts/bazel.sh'), *arguments], env=env, check=True)
            return capture.read_text().splitlines()

    def test_default_root_is_left_to_bazel(self):
        self.assertEqual(self.invoke('server', 'query', '//...'),
                         ['--max_idle_secs=120', 'query', '//...'])

    def test_explicit_startup_paths_are_forwarded_in_batch_mode(self):
        self.assertEqual(self.invoke('batch', '--output_base=/tmp/test-base',
                                     '--output_user_root=/tmp/test-user', 'version'),
                         ['--batch', '--output_base=/tmp/test-base',
                          '--output_user_root=/tmp/test-user', 'version'])
