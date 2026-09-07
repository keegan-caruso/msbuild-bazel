"""S01/S04 explicit generator, retaining native build/cache controls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ExplicitGeneration(unittest.TestCase):
    def test_generated_explicit_workspace(self):
        output = Path(tempfile.mkdtemp(prefix='starlark-explicit-')) / 'probe'
        print('Explicit evidence: ' + str(output), file=sys.stderr)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_bazel.py'), '--output', str(output)],
                                cwd=ROOT, text=True, capture_output=True, timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((output / 'report.json').read_text())
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(report['baselineOutput'], 'shared-v1/app-v1')
        for name, executed, expected in (
            ('cold', ['App', 'Shared'], 'shared-v1/app-v1'),
            ('unchanged', [], 'shared-v1/app-v1'),
            ('appEdit', ['App'], 'shared-v1/app-v2'),
            ('sharedEdit', ['App', 'Shared'], 'shared-v2/app-v2'),
            ('diskCache', [], 'shared-v2/app-v2'),
            ('newOutputBase', [], 'shared-v2/app-v2'),
        ):
            case = report['cases'][name]
            self.assertEqual(case['executedProjects'], executed)
            self.assertEqual(case['applicationOutput'], expected)
            self.assertEqual(case['applicationReturncode'], 0)
            self.assertEqual(case['apphostOutput'], expected)
            self.assertEqual(case['apphostReturncode'], 0)
            if name in ('diskCache', 'newOutputBase'):
                self.assertEqual(case['cacheHitProjects'], ['App', 'Shared'])
            for action in case['executions']:
                if not action['cacheHit']:
                    self.assertEqual(action['runner'], 'darwin-sandbox' if sys.platform == 'darwin' else 'linux-sandbox')
                self.assertFalse(action['remotable'])
                self.assertFalse(action['remoteCacheable'])
        self.assertEqual(report['sharedCompiledProjects'], ['Shared'])
        self.assertEqual(report['appCompiledProjects'], ['App'])
        self.assertFalse(report['appHasSharedSources'])
        self.assertNotEqual(report['sharedWorkspace'], report['appWorkspace'])
        self.assertNotEqual(report['undeclaredInput']['returncode'], 0)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-starlark.py'),
                                 '--workspace', str(output / 'workspace')], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
