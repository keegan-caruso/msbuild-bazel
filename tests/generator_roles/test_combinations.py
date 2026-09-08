"""Native package/project combinations and independent diagnostic analyzer delivery."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_generator_combinations import CombinationProbe


class GeneratorCombinations(unittest.TestCase):
    def test_delivery_diagnostics_selected_framework_and_recovered_compilation(self):
        for delivery in ('project', 'package'):
            with self.subTest(delivery=delivery):
                output = Path(tempfile.mkdtemp(prefix='generator-combinations-')).resolve() / delivery
                print('Generator combinations evidence: ' + str(output), flush=True)
                report = CombinationProbe(output, delivery).execute()
                self.assertTrue(report['accepted'])
                self.assertEqual(set(report['cases']), {'cold', 'unchanged', 'classic',
                    'packageUpgrade', 'analyzerUpgrade', 'suppressedAnalyzer',
                    'errorAnalyzer', 'analyzerWarningsAsErrors', 'relocated', 'recoveredConsumer'})
                self.assertEqual(report['cases']['suppressedAnalyzer']['analyzerDiagnostic'], 'none')
                for name in ('errorAnalyzer', 'analyzerWarningsAsErrors'):
                    self.assertEqual(report['cases'][name]['analyzerDiagnostic'], 'error')
                    self.assertNotEqual(report['cases'][name]['returncode'], 0)
