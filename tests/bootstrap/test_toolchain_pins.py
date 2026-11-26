"""Architecture selection must preserve the baseline and reject unknown hosts."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from toolchain_pins import select


class ToolchainPinsTests(unittest.TestCase):
    def setUp(self):
        self.pins = json.loads((ROOT / 'scripts/toolchains.json').read_text())

    def test_x64_keeps_existing_downloads(self):
        for name, pin in select(self.pins, 'x86_64').items():
            self.assertEqual(pin, {key: self.pins[name][key] for key in ('version', 'url', 'sha256')})

    def test_arm64_uses_distinct_downloads_at_same_versions(self):
        arm = select(self.pins, 'aarch64')
        self.assertEqual(arm, select(self.pins, 'arm64'))
        for name, pin in arm.items():
            self.assertEqual(pin['version'], self.pins[name]['version'])
            self.assertNotEqual(pin['sha256'], self.pins[name]['sha256'])
            self.assertIn('linux-arm64', pin['url'])

    def test_windows_x64_uses_zip_and_executable(self):
        selected = select(self.pins, 'AMD64', 'Windows')
        self.assertEqual(selected, select(self.pins, 'x86_64', 'Windows'))
        self.assertTrue(selected['dotnet']['url'].endswith('-win-x64.zip'))
        self.assertTrue(selected['bazelisk']['url'].endswith('-windows-amd64.exe'))

    def test_windows_arm64_selects_native_tools(self):
        for arch in ('ARM64', 'arm64', 'aarch64'):
            selected = select(self.pins, arch, 'Windows')
            self.assertTrue(selected['dotnet']['url'].endswith('-win-arm64.zip'))
            self.assertTrue(selected['bazelisk']['url'].endswith('-windows-arm64.exe'))

    def test_unknown_architecture_does_not_fall_back_to_x64(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported bootstrap platform'):
            select(self.pins, 'riscv64')

    def test_missing_arm_pin_does_not_fall_back_to_x64(self):
        del self.pins['dotnet']['platforms']['linux-arm64']
        with self.assertRaises(KeyError):
            select(self.pins, 'aarch64')

    def test_macos_selects_native_downloads(self):
        selected = select(self.pins, 'arm64', 'Darwin')
        self.assertIn('osx-arm64', selected['dotnet']['url'])
        self.assertIn('darwin-arm64', selected['bazelisk']['url'])

    def test_unknown_operating_system_is_rejected(self):
        with self.assertRaises(ValueError):
            select(self.pins, 'arm64', 'UnknownOS')
