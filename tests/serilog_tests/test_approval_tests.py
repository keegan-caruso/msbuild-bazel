"""Opt-in unchanged upstream test-project acceptance with real xunit results."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_serilog_tests import ordinary_probe


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE') and os.environ.get('SPIKE_SERILOG_PACKAGES'),
    'requires acquired pinned source and packages')
class SerilogApprovalAcceptance(unittest.TestCase):
    def test_ordinary_one_fact_and_nonzero_failure_controls(self):
        output = Path(tempfile.mkdtemp(prefix='serilog-test-ordinary-')).resolve() / 'probe'
        report = ordinary_probe(os.environ['SPIKE_SERILOG_SOURCE'], os.environ['SPIKE_SERILOG_PACKAGES'], output)
        self.assertTrue(report['accepted'])
        self.assertEqual(report['cases']['ordinary-pass']['passed'], 1)
        for case in ('ordinary-mismatch', 'ordinary-missing-approved', 'ordinary-exception'):
            self.assertEqual(report['cases'][case]['failed'], 1)
            self.assertEqual(report['cases'][case]['executed'], 1)
        print('Ordinary approval test evidence: ' + str(output), flush=True)


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE') and os.environ.get('SPIKE_SERILOG_PACKAGES') and
    os.environ.get('SPIKE_SERILOG_NATIVE_TESTS') == '1', 'requires opt-in native test action qualification')
class SerilogNativeApprovalAcceptance(unittest.TestCase):
    def test_native_one_fact_failure_worksets_and_recovery(self):
        from probe_serilog_test_adapter import probe
        output = Path(tempfile.mkdtemp(prefix='serilog-native-tests-')).resolve() / 'probe'
        report = probe(os.environ['SPIKE_SERILOG_SOURCE'], os.environ['SPIKE_SERILOG_PACKAGES'], output)
        self.assertTrue(report['accepted'])
        self.assertEqual(set(report['rejections']), {'missing-source','changed-source','missing-package','changed-package','missing-testdata'})
        self.assertEqual(report['cases']['cold']['result']['passed'], 1)
        self.assertEqual(report['cases']['relocated']['result']['passed'], 1)
        self.assertTrue(report['cases']['relocated']['testExecuted'])
        self.assertTrue(report['cases']['relocated']['producerStateAbsentBeforeBuild'])
        print('Native approval test evidence: ' + str(output), flush=True)
