"""Focused .NET runner contracts, subprocess pipes and cancellation."""
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOTNET = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')) / 'dotnet'


class ActionRunnerTests(unittest.TestCase):
    def test_contracts_and_process_lifetime(self):
        result = subprocess.run(
            [str(DOTNET), 'run', '--project', str(ROOT / 'tests/ActionRunner.Tests'), '-c', 'Release'],
            cwd=ROOT, text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Action runner contract and process tests passed.', result.stdout)
