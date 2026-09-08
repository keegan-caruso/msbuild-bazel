"""Native R05 generator/reference-role mutation and recovery acceptance."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_generator_roles import probe, PROJECTS


class NativeGeneratorRoles(unittest.TestCase):
    def test_generated_apis_roles_diagnostics_and_producer_free_recovery(self):
        output = Path(tempfile.mkdtemp(prefix='generator-roles-native-')).resolve() / 'probe'
        print('Native generator-role evidence: ' + str(output), flush=True)
        report = probe(output)
        self.assertTrue(report['accepted'])
        cases = report['cases']
        self.assertEqual(set(cases), {'cold', 'unchanged', 'classic', 'incremental', 'additional',
            'removed', 'property', 'editorconfig', 'suppressed', 'severityError',
            'warningsAsErrors', 'orderOnly', 'generatorFailure', 'relocated', 'recoveredConsumer'})
        self.assertEqual(cases['relocated']['bundleFiles'], cases['cold']['bundleFiles'])
        self.assertTrue(cases['relocated']['producerStateAbsentBeforeBuild'])
        self.assertEqual({action['project'] for action in cases['cold']['actions']}, PROJECTS)
        for case in ('severityError', 'warningsAsErrors'):
            self.assertNotEqual(cases[case]['returncode'], 0)
            self.assertEqual(cases[case]['diagnostics'], ['GEN001', 'GEN002'])
        for name, case in cases.items():
            self.assertTrue(case['preparationWorkspaceAbsent'], name)


if __name__ == '__main__':
    unittest.main()
