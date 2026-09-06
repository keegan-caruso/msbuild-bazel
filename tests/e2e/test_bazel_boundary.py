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

    def test_pinned_package_inputs(self):
        self.run_probe(False, True)

    def test_deterministic_staging(self):
        self.run_probe(False, staging=True)

    @unittest.skipUnless(os.environ.get('SPIKE_NATIVE_RUNTIME_TEST') == '1',
                         'opt in with SPIKE_NATIVE_RUNTIME_TEST=1 inside nix develop')
    def test_native_runtime_closure(self):
        self.run_probe(False, native_runtime=True)

    def run_probe(self, identity, packages=False, staging=False, native_runtime=False):
        directory = Path(tempfile.mkdtemp(prefix='msbuild-e2e-bazel-')).resolve()
        try:
            completed = subprocess.run([sys.executable, str(ROOT / 'tools/probe_bazel.py'),
                                        '--output', str(directory / 'probe'), *(['--identity-probe'] if identity else []), *(['--package-probe'] if packages else []), *(['--staging-probe'] if staging else []), *(['--native-runtime-probe'] if native_runtime else [])],
                                       text=True, capture_output=True, timeout=900)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads((directory / 'probe/report.json').read_text())
            self.assertEqual(report['baselineOutput'], 'shared-v1/data-v1/import-v1/env-v1/app-v1' if identity else ('shared-v1/package-v1/target-v1/app-v1' if packages else 'shared-v1/app-v1'))
            self.assertTrue(report['preparationWorkspaceAbsent'])
            self.assertEqual(report['sdkVersion'], '10.0.100')
            if native_runtime:
                self.assertGreater(report['nativeRuntime']['fileCount'], 0)
                self.assertGreater(len(report['nativeRuntime']['storePaths']), 2)
                self.assertNotEqual(report['missingNativeRuntime']['returncode'], 0)
                for action in report['cases']['cold']['executions']:
                    self.assertIn('runtime-closure.json', action['inputs'])
                    self.assertTrue(any('/lib/lib' in path and ('dylib' in path or '.so' in path)
                                        for path in action['inputs']))
            if staging:
                self.assertEqual(report['staging']['differences'], {'shared': [], 'app': []})
                self.assertEqual(report['staging']['before'], report['staging']['after'])
                self.assertTrue(report['staging']['workspacePathsDiffer'])
                fresh = report['cases']['freshExecution']
                self.assertEqual(fresh['executedProjects'], ['App', 'Shared'])
                self.assertEqual(fresh['cacheHitProjects'], [])
                self.assertEqual(fresh['applicationOutput'], report['baselineOutput'])
                self.assertEqual(fresh['apphostOutput'], report['baselineOutput'])
                for execution in fresh['executions']:
                    self.assertIn('sandbox', execution['runner'])
                for files in report['staging']['after'].values():
                    self.assertNotIn('action.json', files)
                    self.assertNotIn('build.log', files)
                    self.assertFalse(any('FileListAbsolute' in name for name in files))
                self.assertTrue(report['staging']['after']['app']['artifacts/App/bin/Release/net10.0/App']['executable'])
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
                if packages:
                    output = output.replace('/app-', '/package-v1/target-v1/app-')
                observed = report['cases'][name]
                self.assertEqual(observed['executedProjects'], executed, observed)
                self.assertEqual(observed['applicationOutput'], output, observed)
                self.assertEqual(observed['applicationReturncode'], 0, observed)
                self.assertEqual(observed['apphostReturncode'], 0, observed)
                self.assertEqual(observed['apphostOutput'], output, observed)
                if packages:
                    self.assertEqual(observed['packageTargets'], {project: ['Shared'] if project == 'Shared' else [] for project in executed})
                for action in observed['executions']:
                    if not action['cacheHit']:
                        self.assertIn('sandbox', action['runner'])
                if name in ('diskCache', 'newOutputBase'):
                    self.assertEqual(observed['cacheHitProjects'], ['App', 'Shared'], observed)
            for action in report['cases']['cold']['executions']:
                self.assertTrue(any('/sdk/sdk/10.0.100/Microsoft.Build.dll' in path for path in action['inputs']))
                self.assertIn('ReplayPlugin.dll', action['inputs'])
                self.assertIn('host-identity.json', action['inputs'])
                self.assertFalse(any('/stdlib/' in path or '+python/' in path for path in action['inputs']))
                self.assertTrue(action['commandArgs'][0].endswith('/sdk/dotnet'))
                self.assertEqual(action['commandArgs'][1:3], ['runner/ActionRunner.dll', '--request'])
                for name in ('ActionRunner.dll', 'ActionRunner.deps.json', 'ActionRunner.runtimeconfig.json', 'Action.props', 'Action.targets'):
                    self.assertIn('runner/' + name, action['inputs'])
                self.assertFalse(action['remotable'])
                self.assertFalse(action['remoteCacheable'])
                self.assertIn('src/Directory.Build.targets', action['inputs'])
                if action['project'] == 'App':
                    self.assertFalse(any('shared.diagnostics' in path.split('/') for path in action['inputs']))
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
                    ('policyEdit', ['App', 'Shared'], '/data-v2/import-v2/env-v2'),
                ):
                    observed = report['cases'][name]
                    self.assertEqual(observed['executedProjects'], executed, name)
                    self.assertEqual(observed['applicationOutput'], 'shared-v2' + suffix + '/app-v2', name)
                    self.assertEqual(observed['apphostOutput'], observed['applicationOutput'])
            if packages:
                for name, suffix in (('packageDataVersion', 'package-v2/target-v1'),
                                     ('packageTargetVersion', 'package-v2/target-v2')):
                    observed = report['cases'][name]
                    self.assertEqual(observed['executedProjects'], ['App', 'Shared'])
                    self.assertEqual(observed['applicationOutput'], 'shared-v2/' + suffix + '/app-v2')
                    self.assertEqual(observed['apphostOutput'], observed['applicationOutput'])
                    self.assertEqual(observed['packageTargets'], {'Shared': ['Shared'], 'App': []})
                self.assertEqual(report['packageTargets'], {'Shared': ['Shared'], 'App': []})
                for name in ('missingPackage', 'corruptPackage', 'stalePackageRestore'):
                    failure = report[name]
                    self.assertNotEqual(failure['returncode'], 0)
                    log = Path(failure['log']).read_text()
                    self.assertIn('package', log.lower())
                    self.assertNotIn('SPIKE_COMPILE:', log)
                self.assertEqual(report['packagePreparationDeleted'], [True, True, True])
                self.assertFalse((directory / 'probe/workspace/src/package-feed').exists())
                for action in report['cases']['cold']['executions']:
                    self.assertIn(f"package-manifests/{action['project']}.json", action['inputs'])
                    self.assertIn('packages/spike.buildinputs/1.0.0/build/Spike.BuildInputs.targets', action['inputs'])
                    self.assertIn('packages/spike.buildinputs/1.0.0/data/value.txt', action['inputs'])
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
