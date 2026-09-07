"""Opt-in native test-rule protocol; the graph-built upstream gate is separate."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_test_action import probe


SOURCE = os.environ.get('RULES_MSBUILD_SERILOG_SOURCE') or os.environ.get('SERILOG_SOURCE')
PACKAGES = os.environ.get('RULES_MSBUILD_SERILOG_PACKAGES') or os.environ.get('SERILOG_PACKAGES')


@unittest.skipUnless(SOURCE and PACKAGES,
                     'set RULES_MSBUILD_SERILOG_SOURCE and RULES_MSBUILD_SERILOG_PACKAGES to pinned acquired upstream inputs')
class NativeTestRule(unittest.TestCase):
    def test_retained_results_and_no_source_checkout(self):
        parent = Path(tempfile.mkdtemp(prefix='msbuild-test-action-')).resolve()
        report = probe(SOURCE, PACKAGES, parent / 'probe')
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(set(report['cases']), {'pass', 'changed', 'missing', 'zeroTests'})
        self.assertEqual(report['cases']['pass']['report']['successful'], 1)
        self.assertEqual(report['cases']['changed']['report']['failed'], 1)
        self.assertEqual(report['cases']['missing']['report']['failed'], 1)
        self.assertEqual(report['cases']['zeroTests']['report']['total'], 0)
