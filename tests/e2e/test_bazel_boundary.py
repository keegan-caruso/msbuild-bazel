"""Real Bazel scheduling, sandbox and local disk-cache acceptance."""
import json
import os
import stat
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BazelBoundaryTests(unittest.TestCase):
    def test_two_project_actions(self):
        self.run_probe(False)

    def test_action_identity_inputs(self):
        self.run_probe(True)

    def run_probe(self, identity):
        directory = Path(tempfile.mkdtemp(prefix='msbuild-e2e-bazel-')).resolve()
        try:
            completed = subprocess.run([sys.executable, str(ROOT / 'tools/probe_bazel.py'),
                                        '--output', str(directory / 'probe'), *(['--identity-probe'] if identity else [])],
                                       text=True, capture_output=True, timeout=900)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads((directory / 'probe/report.json').read_text())
            self.assertEqual(report['baselineOutput'], 'shared-v1/data-v1/import-v1/env-v1/app-v1' if identity else 'shared-v1/app-v1')
            self.assertTrue(report['preparationWorkspaceAbsent'])
            self.assertEqual(report['sdkVersion'], '10.0.100')
            for name, executed, output in (
                ('cold', ['App', 'Shared'], 'shared-v1/app-v1'),
                ('unchanged', [], 'shared-v1/app-v1'),
                ('appEdit', ['App'], 'shared-v1/app-v2'),
                ('sharedEdit', ['App', 'Shared'], 'shared-v2/app-v2'),
                ('diskCache', [], 'shared-v2/app-v2'),
                ('newOutputBase', [], 'shared-v2/app-v2'),
            ):
                if identity:
                    output = output.replace('/app-', '/data-v1/import-v1/env-v1/app-')
                observed = report['cases'][name]
                self.assertEqual(observed['executedProjects'], executed, observed)
                self.assertEqual(observed['applicationOutput'], output, observed)
                self.assertEqual(observed['applicationReturncode'], 0, observed)
                self.assertEqual(observed['apphostReturncode'], 0, observed)
                self.assertEqual(observed['apphostOutput'], output, observed)
                for action in observed['executions']:
                    if not action['cacheHit']:
                        self.assertIn('sandbox', action['runner'])
                if name in ('diskCache', 'newOutputBase'):
                    self.assertEqual(observed['cacheHitProjects'], ['App', 'Shared'], observed)
            for action in report['cases']['cold']['executions']:
                self.assertTrue(any('/sdk/sdk/10.0.100/Microsoft.Build.dll' in path for path in action['inputs']))
                self.assertIn('ReplayPlugin.dll', action['inputs'])
                self.assertIn('host-identity.json', action['inputs'])
                self.assertTrue(any('/stdlib/json/__init__.py' in path for path in action['inputs']))
                self.assertEqual(action['commandArgs'][1:4], ['-I', '-S', '-B'])
                self.assertFalse(action['remotable'])
                self.assertFalse(action['remoteCacheable'])
                self.assertIn('src/Directory.Build.targets', action['inputs'])
                if action['project'] == 'App':
                    self.assertFalse(any(path.startswith('src/Shared/') and path.endswith('.cs') for path in action['inputs']))
                    self.assertNotIn('src/Shared/value.txt', action['inputs'])
                else:
                    self.assertFalse(any(path.startswith('src/App/') for path in action['inputs']))
            if identity:
                for name, executed, suffix in (
                    ('importEdit', ['App', 'Shared'], '/data-v1/import-v2/env-v1'),
                    ('dataEdit', ['App', 'Shared'], '/data-v2/import-v2/env-v1'),
                    ('environmentEdit', ['App', 'Shared'], '/data-v2/import-v2/env-v2'),
                    ('ambientEnvironment', [], '/data-v2/import-v2/env-v2'),
                    ('restoreEdit', ['App'], '/data-v2/import-v2/env-v2'),
                    ('hostIdentityEdit', ['App', 'Shared'], '/data-v2/import-v2/env-v2'),
                ):
                    observed = report['cases'][name]
                    self.assertEqual(observed['executedProjects'], executed, name)
                    self.assertEqual(observed['applicationOutput'], 'shared-v2' + suffix + '/app-v2', name)
                    self.assertEqual(observed['apphostOutput'], observed['applicationOutput'])
            self.assertNotEqual(report['sharedWorkspace'], report['appWorkspace'])
            self.assertFalse(report['appHasSharedSources'])
            self.assertNotEqual(report['undeclaredInput']['returncode'], 0)
            self.assertEqual(report['sharedCompiledProjects'], ['Shared'])
            self.assertEqual(report['appCompiledProjects'], ['App'])
        except BaseException:
            print(f'Retained Bazel workspace: {directory}', file=sys.stderr)
            raise
        else:
            # Bazel makes output directories read-only. Change only directories
            # owned by this test; never follow SDK or execroot symlinks.
            for current, _, _ in os.walk(directory, followlinks=False):
                path = Path(current)
                path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR | stat.S_IXUSR)
            shutil.rmtree(directory)
