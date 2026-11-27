"""Fixture launch selection must preserve native arguments and explicit opt-ins."""
import os
import sys
import unittest
from unittest.mock import patch

import fixture_host

sys.path.insert(0, str(fixture_host.ROOT / "tests"))
import fixture_sdk


class FixtureHost(unittest.TestCase):
    def test_windows_native_override_and_literal_arguments(self):
        with patch.object(fixture_host, 'WINDOWS', True), patch.dict(os.environ,
                {'RULES_MSBUILD_BAZEL': r'C:\tools space\bazel.exe'}, clear=True):
            self.assertEqual(fixture_host.bazel_startup('--output_base=C:/space directory', 'build'),
                [r'C:\tools space\bazel.exe', '--output_base=C:/space directory', 'build'])

    def test_windows_shell_override_requires_explicit_interpreter(self):
        with patch.object(fixture_host, 'WINDOWS', True), patch.dict(os.environ,
                {'RULES_MSBUILD_BAZEL': 'C:/rules/scripts/bazel-launcher.sh'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'RULES_MSBUILD_BASH'):
                fixture_host.bazel_startup('build')
            os.environ['RULES_MSBUILD_BASH'] = 'C:/Git/bin/bash.exe'
            self.assertEqual(fixture_host.bazel_startup('build')[:2],
                ['C:/Git/bin/bash.exe', 'C:/rules/scripts/bazel-launcher.sh'])

    def test_decoded_windows_report_cannot_hide_absolute_paths(self):
        with patch.object(fixture_host, 'WINDOWS', True):
            fixture_host.assert_no_host_paths({'references': ['{sdk}/ref.dll']}, r'C:\tools\sdk')
            for leaked in [r'C:\tools\sdk\ref.dll', 'c:/TOOLS/sdk/ref.dll']:
                with self.assertRaises(AssertionError):
                    fixture_host.assert_no_host_paths({'references': [leaked]}, r'C:\tools\sdk')

    def test_platform_is_explicit_only_on_windows(self):
        with patch.object(fixture_host, 'WINDOWS', True), patch.object(fixture_host.platform, 'machine') as machine:
            for architecture, platform in [('AMD64', 'win-x64'), ('x86_64', 'win-x64'), ('ARM64', 'win-arm64'), ('aarch64', 'win-arm64')]:
                machine.return_value = architecture
                self.assertIn('platforms=["' + platform + '"]', fixture_host.sdk_declaration(global_json='//:global.json'))
            machine.return_value = 'unknown'
            with self.assertRaisesRegex(ValueError, 'Unsupported Windows fixture architecture'):
                fixture_host.sdk_declaration(version='11.0.100')
        with patch.object(fixture_host, 'WINDOWS', False):
            self.assertNotIn('platforms=', fixture_host.sdk_declaration(version='11.0.100'))
        with self.assertRaises(ValueError):
            fixture_host.sdk_declaration(version='11.0.100', global_json='//:global.json')

    def test_bazel_environment_uses_repository_pin_and_preserves_override(self):
        with patch.dict(os.environ, {}, clear=True):
            expected = (fixture_host.ROOT / '.bazelversion').read_text().strip()
            self.assertEqual(fixture_host.bazel_environment()['USE_BAZEL_VERSION'], expected)
            self.assertEqual(fixture_host.bazel_environment(USE_BAZEL_VERSION='')['USE_BAZEL_VERSION'], expected)
            self.assertEqual(fixture_host.bazel_environment(USE_BAZEL_VERSION='8.8.0')['USE_BAZEL_VERSION'], '8.8.0')
        with patch.dict(os.environ, {'USE_BAZEL_VERSION': '9.3.3'}, clear=True):
            self.assertEqual(fixture_host.bazel_environment()['USE_BAZEL_VERSION'], '9.3.3')

    def test_ordinary_fixture_sdk_supports_native_windows_architectures(self):
        with patch.object(fixture_sdk.platform, 'system', return_value='Windows'), patch.object(fixture_sdk.platform, 'machine') as machine:
            for architecture, platform in [('AMD64', 'win-x64'), ('ARM64', 'win-arm64')]:
                machine.return_value = architecture
                self.assertIn('platforms=["' + platform + '"]', fixture_sdk.sdk_declarations(version='11.0.100'))
            machine.return_value = 'unknown'
            with self.assertRaisesRegex(ValueError, 'Unsupported fixture SDK platform'):
                fixture_sdk.sdk_declarations()


if __name__ == '__main__':
    unittest.main()
