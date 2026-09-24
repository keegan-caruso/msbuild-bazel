"""Version selection survives generated workspaces and preserves startup arguments."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BazelLauncherTests(unittest.TestCase):
    def invoke(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root/'repo'; (repo/'scripts').mkdir(parents=True)
            for name in ('env.sh', 'bazel-launcher.sh'):
                shutil.copy2(ROOT/'scripts'/name, repo/'scripts'/name)
            (repo/'.bazelversion').write_text('9.2.0\n')
            workspace = root/'generated'; workspace.mkdir()
            (workspace/'.bazelversion').write_text('0.0.0\n')
            fake = root/'bazelisk'
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$USE_BAZEL_VERSION" "$PWD" "$@"\n')
            fake.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k not in ('USE_BAZEL_VERSION', 'RULES_MSBUILD_BAZEL_VERSION')}
            env.update(RULES_MSBUILD_BAZELISK=str(fake), **overrides)
            result = subprocess.run([str(repo/'scripts/bazel-launcher.sh'), '--batch', 'version'],
                                    cwd=workspace, env=env, text=True, capture_output=True, check=True)
            version, cwd, *arguments = result.stdout.splitlines()
            self.assertEqual(Path(cwd).resolve(), workspace.resolve())
            self.assertEqual(arguments, ['--batch', 'version'])
            return version

    def test_default_ignores_unrelated_workspace_pin(self):
        self.assertEqual(self.invoke(), '9.2.0')

    def test_bazelisk_override_selects_compatibility_version(self):
        self.assertEqual(self.invoke(USE_BAZEL_VERSION='8.8.0'), '8.8.0')

    def test_legacy_override_is_preserved(self):
        self.assertEqual(self.invoke(RULES_MSBUILD_BAZEL_VERSION='8.8.0'), '8.8.0')

    def test_bazelisk_override_takes_precedence(self):
        self.assertEqual(self.invoke(USE_BAZEL_VERSION='8.8.0', RULES_MSBUILD_BAZEL_VERSION='9.2.0'), '8.8.0')
