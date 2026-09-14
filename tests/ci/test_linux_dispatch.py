"""Exercise CI phase selection without downloading tools or executing builds."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LinuxDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'scripts').mkdir()
        shutil.copy(ROOT / 'scripts/ci-linux.sh', self.root / 'scripts/ci-linux.sh')
        (self.root / 'tests/e2e').mkdir(parents=True)
        for source in (ROOT / 'tests/e2e').glob('test_*.py'):
            (self.root / 'tests/e2e' / source.name).touch()
        commands = self.root / 'commands'
        commands.mkdir()
        for name in ('git', 'bash', 'python3'):
            command = commands / name
            command.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = [Path(sys.argv[0]).name, *sys.argv[1:]]
with open(os.environ['CI_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if os.environ.get('CI_TEST_FAIL') in args:
    sys.exit(17)
''')
            command.chmod(0o755)
        self.log = self.root / 'commands.jsonl'
        self.env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH'],
                        CI_TEST_LOG=str(self.log))

    def run_phase(self, phase, fail=''):
        result = subprocess.run(['/bin/bash', str(self.root / 'scripts/ci-linux.sh'), phase],
                                env=dict(self.env, CI_TEST_FAIL=fail), capture_output=True, text=True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
        return result, calls

    def test_quick_omits_native_acceptance(self):
        result, calls = self.run_phase('quick')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any('test_action_runner.py' in call for call in calls))
        self.assertTrue(any('tests/graph' in call for call in calls))
        self.assertTrue(any('tests/preparation_reuse' in call for call in calls))
        self.assertFalse(any('tests/graph_execution' in call for call in calls))
        self.assertFalse(any('test_bazel_boundary.py' in call for call in calls))

    def test_full_runs_e2e_modules_once(self):
        result, calls = self.run_phase('full')
        self.assertEqual(result.returncode, 0, result.stderr)
        modules = [call[call.index('-p') + 1] for call in calls if '-p' in call]
        self.assertCountEqual(modules, [p.name for p in (ROOT / 'tests/e2e').glob('test_*.py')])
        self.assertEqual(sum('tests/graph' in call for call in calls), 1)
        self.assertEqual(sum('tests/graph_execution' in call for call in calls), 1)

    def test_quick_failure_stops_full(self):
        result, calls = self.run_phase('full', fail='scripts/check-dotnet.sh')
        self.assertEqual(result.returncode, 17)
        self.assertFalse(any('tests/graph_execution' in call for call in calls))
        self.assertFalse(any('test_bazel_boundary.py' in call for call in calls))

    def test_acceptance_does_not_repeat_quick(self):
        result, calls = self.run_phase('acceptance')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any('test_action_runner.py' in call for call in calls))
        self.assertFalse(any('tests/graph' in call for call in calls))
        self.assertTrue(any('tests/graph_execution' in call for call in calls))

    def test_unknown_scope_runs_nothing(self):
        result, calls = self.run_phase('typo')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])
