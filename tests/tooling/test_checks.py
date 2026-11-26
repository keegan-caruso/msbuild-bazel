"""Toolchain checks run without the retired preparation controller or build graph."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOTNET = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))/('dotnet.exe' if os.name == 'nt' else 'dotnet')
TOOL = ROOT/'tools/Tooling/bin/Release/net11.0/Tooling.dll'


class ToolChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != 'nt':
            return
        cls.probe_directory = tempfile.TemporaryDirectory(prefix='native-tool-version-')
        cls.addClassCleanup(cls.probe_directory.cleanup)
        root = Path(cls.probe_directory.name)
        (root/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework>'
            '<UseAppHost>true</UseAppHost></PropertyGroup></Project>')
        (root/'Program.cs').write_text('System.Console.WriteLine(System.IO.File.ReadAllText('
            'System.Environment.ProcessPath + ".version"));')
        environment = dict(os.environ, DOTNET_ROOT=str(DOTNET.parent),
                           DOTNET_CLI_USE_MSBUILD_SERVER='false', MSBUILDUSESERVER='0',
                           MSBUILDDISABLENODEREUSE='1')
        result = subprocess.run([str(DOTNET), 'build', str(root/'Probe.csproj'),
                                 '-p:UseSharedCompilation=false', '--nologo'],
                                env=environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.probe_output = root/'bin/Debug/net11.0'

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
        self.bazel = self.root/('bazel.exe' if os.name == 'nt' else 'bazel')
        self.executable(self.bazel, 'bazel 9.3.2')
        self.env = dict(os.environ, DOTNET_ROOT=str(self.sdk), RULES_MSBUILD_BAZEL=str(self.bazel), USE_BAZEL_VERSION='9.3.2')
        if os.name == 'nt':
            # Run the fake apphosts on the verified test SDK, while Tooling reads
            # the independent DOTNET_ROOT under test. Architecture roots take precedence.
            self.env.update(DOTNET_ROOT_X64=str(DOTNET.parent), DOTNET_ROOT_ARM64=str(DOTNET.parent))

    def executable(self, path, value):
        if os.name == 'nt':
            path = path.with_suffix('.exe')
            for source in self.probe_output.iterdir():
                if source.is_file():
                    shutil.copy2(source, path.parent/source.name)
            shutil.copy2(self.probe_output/'Probe.exe', path)
            Path(str(path)+'.version').write_text(value)
            return
        path.write_text('#!/bin/sh\necho "'+value+'"\n'); path.chmod(0o755)

    def check(self):
        return subprocess.run([str(DOTNET), str(TOOL), str(self.root), 'check', '--toolchain-only'],
                              env=self.env, capture_output=True, text=True)

    def test_selected_versions_without_preparation(self):
        for version in ['9.3.2']:
            self.executable(self.bazel, 'bazel '+version)
            self.env['USE_BAZEL_VERSION'] = version
            result = self.check()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Toolchain checks passed', result.stdout)

    def test_repository_pin_ignores_legacy_override(self):
        self.env.pop('USE_BAZEL_VERSION')
        self.env['RULES_MSBUILD_BAZEL_VERSION'] = '0.0.0'
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_override_uses_repository_pin(self):
        self.env['USE_BAZEL_VERSION'] = ''
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_binary_is_rejected(self):
        self.env['USE_BAZEL_VERSION'] = '0.0.0'
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
