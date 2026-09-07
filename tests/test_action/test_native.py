"""Opt-in native test-rule protocol; the graph-built upstream gate is separate."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_test_action import probe


@unittest.skipUnless(os.environ.get('SERILOG_SOURCE') and os.environ.get('SERILOG_PACKAGES'),
                     'set SERILOG_SOURCE and SERILOG_PACKAGES to pinned acquired upstream inputs')
class NativeTestRule(unittest.TestCase):
    def test_retained_results_and_no_source_checkout(self):
        parent = Path(tempfile.mkdtemp(prefix='msbuild-test-action-')).resolve()
        report = probe(os.environ['SERILOG_SOURCE'], os.environ['SERILOG_PACKAGES'], parent / 'probe')
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(set(report['cases']), {'pass', 'changed', 'missing', 'zeroTests'})
        self.assertEqual(report['cases']['pass']['report']['successful'], 1)
        self.assertEqual(report['cases']['changed']['report']['failed'], 1)
        self.assertEqual(report['cases']['missing']['report']['failed'], 1)
        self.assertEqual(report['cases']['zeroTests']['report']['total'], 0)
