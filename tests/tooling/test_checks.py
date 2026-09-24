"""Toolchain checks run without the retired preparation controller or build graph."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOTNET = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))/'dotnet'
TOOL = ROOT/'tools/Tooling/bin/Release/net10.0/Tooling.dll'


class ToolChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'scripts').mkdir()
        for name in ['global.json', '.bazelversion', 'scripts/toolchains.json', 'scripts/toolchain-pins.sh', 'scripts/starlark-tools.json']:
            shutil.copyfile(ROOT/name, self.root/name)
        self.sdk = self.root/'sdk'; self.sdk.mkdir()
        version = json.loads((ROOT/'global.json').read_text())['sdk']['version']
        self.executable(self.sdk/'dotnet', version)
        self.bazel = self.root/'bazel'
        self.executable(self.bazel, 'bazel 8.8.0')
        self.env = dict(os.environ, DOTNET_ROOT=str(self.sdk), RULES_MSBUILD_BAZEL=str(self.bazel), RULES_MSBUILD_BAZEL_VERSION='8.8.0')
        self.env.pop('RULES_MSBUILD_CONTAINER_PREBUILT', None)

    def executable(self, path, value):
        path.write_text('#!/bin/sh\necho "'+value+'"\n'); path.chmod(0o755)

    def check(self):
        return subprocess.run([str(DOTNET), str(TOOL), str(self.root), 'check', '--toolchain-only'],
                              env=self.env, capture_output=True, text=True)

    def test_selected_versions_without_preparation(self):
        for version in ['8.8.0', '9.2.0']:
            self.executable(self.bazel, 'bazel '+version)
            self.env['RULES_MSBUILD_BAZEL_VERSION'] = version
            result = self.check()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Toolchain checks passed', result.stdout)

    def test_wrong_binary_is_rejected(self):
        self.env['RULES_MSBUILD_BAZEL_VERSION'] = '9.2.0'
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Bazel version differs', result.stderr)

    def test_wrong_sdk_is_rejected(self):
        self.executable(self.sdk/'dotnet', '0.0.0')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SDK version differs', result.stderr)

    def test_shell_pin_drift_is_rejected(self):
        (self.root/'scripts/toolchain-pins.sh').write_text('')
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Bootstrap pin differs', result.stderr)
