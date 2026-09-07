"""Ordinary SDK oracle for generated-graph package PrivateAssets decisions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from graph_private_assets import DEFAULT_PRIVATE_ASSETS, probe


class PrivateAssetsBaseline(unittest.TestCase):
    def test_left_only_package_compile_and_runtime_flow(self):
        evidence = Path(tempfile.mkdtemp(prefix='graph-private-assets-')).resolve() / 'probe'
        report = probe(evidence)
        print('PrivateAssets evidence: ' + str(evidence), flush=True)
        self.assertEqual(report['schemaVersion'], 1)
        expected_packages = ['RulesMsbuild.Binary/1.0.0', 'RulesMsbuild.Leaf/1.0.0']
        self.assertEqual(report['cases']['default']['privateAssets'], DEFAULT_PRIVATE_ASSETS)
        for name, case in report['cases'].items():
            with self.subTest(private_assets=name):
                self.assertEqual(case['nodes']['Left']['packages'], expected_packages)
                for project in ('Shared', 'Right'):
                    self.assertEqual(case['nodes'][project]['packages'], [])
                for identity, assets in case['nodes']['Left']['assets'].items():
                    assembly = identity.split('/')[0] + '.dll'
                    self.assertEqual(assets['compile'], ['ref/net10.0/' + assembly])
                    self.assertEqual(assets['runtime'], ['lib/net10.0/' + assembly])
                    # Default library copy behavior is distinct from restore availability.
                    self.assertNotIn(assembly, case['nodes']['Left']['outputFiles'])
                for copied in case['packageCopies'].values():
                    self.assertNotEqual(copied['runtimeSha256'], copied['referenceSha256'])
                    self.assertEqual(copied['outputSha256'], None if name == 'all' else copied['runtimeSha256'])
                app = case['nodes']['App']
                if name == 'all':
                    self.assertEqual(app['packages'], [])
                    self.assertNotEqual(case['appDirectPackageCompileReturncode'], 0)
                    self.assertEqual(case['appDirectPackageCompileDiagnostic'], 'CS0103')
                    self.assertNotEqual(case['runtimeReturncode'], 0)
                    self.assertIn('FileNotFoundException', case['runtimeError'])
                    self.assertIn('RulesMsbuild.Binary', case['runtimeError'])
                    self.assertNotIn('RulesMsbuild.Binary.dll', app['outputFiles'])
                    self.assertNotIn('RulesMsbuild.Leaf.dll', app['outputFiles'])
                else:
                    self.assertEqual(app['packages'], expected_packages)
                    self.assertEqual(case['appDirectPackageCompileReturncode'], 0)
                    self.assertEqual(case['runtimeReturncode'], 0, case['runtimeError'])
                    self.assertEqual(case['runtimeOutput'], 'shared-v1:left/package-v1|shared-v1:right')
                    self.assertIn('RulesMsbuild.Binary.dll', app['outputFiles'])
                    self.assertIn('RulesMsbuild.Leaf.dll', app['outputFiles'])
        self.assertEqual(json.loads((evidence / 'report.json').read_text()), report)


if __name__ == '__main__':
    unittest.main()
