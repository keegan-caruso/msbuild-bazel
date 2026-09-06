"""Managed reference/runtime assets and transitive dependency handoff."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BinaryPackageTests(unittest.TestCase):
    def test_binary_package_handoff(self):
        directory = Path(tempfile.mkdtemp(prefix='msbuild-e2e-binary-'))
        completed = subprocess.run(
            [sys.executable, str(ROOT / 'tools/probe_bazel.py'),
             '--binary-package-probe', '--output', str(directory / 'probe')],
            text=True, capture_output=True, timeout=900)
        self.assertEqual(completed.returncode, 0,
                         f'Retained evidence: {directory}\n{completed.stdout}{completed.stderr}')
        report = json.loads((directory / 'probe/report.json').read_text())
        self.assertTrue(report['binaryPackageProbe'])
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(report['packagePreparationDeleted'], [True, True, True])
        self.assertFalse(report['appHasSharedSources'])
        self.assertNotEqual(report['sharedWorkspace'], report['appWorkspace'])
        self.assertEqual(report['baselineOutput'], 'shared-v1/binary-v1/leaf-v1/app-v1')
        cases = [
            ('cold', ['App', 'Shared'], 'shared-v1/binary-v1/leaf-v1/app-v1'),
            ('unchanged', [], 'shared-v1/binary-v1/leaf-v1/app-v1'),
            ('freshExecution', ['App', 'Shared'], 'shared-v1/binary-v1/leaf-v1/app-v1'),
            ('appEdit', ['App'], 'shared-v1/binary-v1/leaf-v1/app-v2'),
            ('sharedEdit', ['App', 'Shared'], 'shared-v2/binary-v1/leaf-v1/app-v2'),
            ('diskCache', [], 'shared-v2/binary-v1/leaf-v1/app-v2'),
            ('newOutputBase', [], 'shared-v2/binary-v1/leaf-v1/app-v2'),
            ('binaryDirectVersion', ['App', 'Shared'], 'shared-v2/binary-v2/leaf-v1/app-v2'),
            ('binaryTransitiveVersion', ['App', 'Shared'], 'shared-v2/binary-v2/leaf-v2/app-v2'),
        ]
        for name, executed, expected in cases:
            with self.subTest(case=name):
                case = report['cases'][name]
                self.assertEqual(case['executedProjects'], executed)
                self.assertEqual(case['applicationOutput'], expected)
                self.assertEqual(case['apphostOutput'], expected)
                self.assertEqual(case['compiledProjects'], {p: [p] for p in executed})
                for action in case['executions']:
                    if not action['cacheHit']:
                        self.assertIn('sandbox', action['runner'])
                    if action['project'] == 'App':
                        self.assertFalse(any(p.startswith('src/Shared/') and p.endswith('.cs')
                                             for p in action['inputs']))
                    for package in ('spike.binary', 'spike.leaf'):
                        self.assertTrue(any(p.startswith('packages/' + package + '/')
                                            and p.endswith('.nupkg.sha512') for p in action['inputs']))
                        for kind in ('ref', 'lib'):
                            self.assertTrue(any(p.startswith('packages/' + package + '/')
                                                and f'/{kind}/net10.0/' in p and p.endswith('.dll')
                                                for p in action['inputs']))
                assets = case['binaryAssets']
                version = '1.0.2' if name == 'binaryTransitiveVersion' else ('1.0.1' if name == 'binaryDirectVersion' else '1.0.0')
                leaf = '1.0.1' if name == 'binaryTransitiveVersion' else '1.0.0'
                self.assertEqual(assets['identities'], ['Spike.Binary/' + version, 'Spike.Leaf/' + leaf])
                for asset in assets['files'].values():
                    self.assertEqual(asset['outputSha256'], asset['runtimeSha256'])
                    self.assertNotEqual(asset['outputSha256'], asset['referenceSha256'])
        for name in ('diskCache', 'newOutputBase'):
            self.assertEqual(report['cases'][name]['cacheHitProjects'], ['App', 'Shared'])
        initial = report['cases']['cold']['binaryAssets']['files']
        direct = report['cases']['binaryDirectVersion']['binaryAssets']['files']
        transitive = report['cases']['binaryTransitiveVersion']['binaryAssets']['files']
        self.assertNotEqual(initial['Spike.Binary.dll']['runtimeSha256'], direct['Spike.Binary.dll']['runtimeSha256'])
        self.assertEqual(initial['Spike.Leaf.dll']['runtimeSha256'], direct['Spike.Leaf.dll']['runtimeSha256'])
        self.assertEqual(direct['Spike.Binary.dll']['runtimeSha256'], transitive['Spike.Binary.dll']['runtimeSha256'])
        self.assertNotEqual(direct['Spike.Leaf.dll']['runtimeSha256'], transitive['Spike.Leaf.dll']['runtimeSha256'])
        self.assertEqual(report['cases']['freshExecution']['cacheHitProjects'], [])
        self.assertTrue(report['staging']['workspacePathsDiffer'])
        self.assertEqual(report['staging']['differences'], {'shared': [], 'app': []})
        for name in ('missingPackage', 'missingPackageMarker', 'corruptPackage', 'stalePackageRestore', 'missingTransitivePackage'):
            self.assertNotEqual(report[name]['returncode'], 0)
            self.assertNotIn('SPIKE_COMPILE:', Path(report[name]['log']).read_text())
        self.assertNotEqual(report['missingRuntimeAsset']['returncode'], 0)
        self.assertIn('Spike.Leaf', Path(report['missingRuntimeAsset']['log']).read_text())
        # Keep evidence for this first milestone run and CI artifact collection.
        print(f'Binary-package evidence: {directory}')
