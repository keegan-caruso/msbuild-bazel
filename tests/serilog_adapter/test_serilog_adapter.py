"""Opt-in real pinned library acceptance; failures remain failures when configured."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_serilog_adapter import probe, REVISION


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE') and os.environ.get('SPIKE_SERILOG_PACKAGES'),
                     'provide the pinned source and acquired package cache; skip is not acceptance')
class SerilogAdapter(unittest.TestCase):
    def test_pinned_library_native_mutations_and_relocation(self):
        output = Path(tempfile.mkdtemp(prefix='serilog-adapter-')) / 'probe'
        print('Serilog adapter evidence: ' + str(output), flush=True)
        report = probe(os.environ['SPIKE_SERILOG_SOURCE'], os.environ['SPIKE_SERILOG_PACKAGES'], output)
        self.assertTrue(report['accepted'])
        self.assertEqual(report['revision'], REVISION)
        self.assertEqual(set(report['cases']), {'cold', 'unchanged', 'source', 'resource', 'key', 'import', 'generatorOption', 'relocated'})
        baseline = report['baselineObservation']
        self.assertEqual(baseline['token'], '24C2F752A8E58A10')
        self.assertTrue(baseline['strongNameSigned'])
        self.assertEqual(baseline['resources'], ['ILLink.Substitutions.xml'])
        self.assertEqual(baseline['logging'], 'Hello "Ada"')
        cases = report['cases']
        self.assertEqual(cases['source']['observation']['nullRendering'], 'NULL')
        self.assertNotEqual(cases['resource']['observation']['resourceHash'], baseline['resourceHash'])
        self.assertNotEqual(cases['key']['observation']['token'], baseline['token'])
        self.assertTrue(cases['key']['observation']['strongNameSigned'])
        self.assertEqual(cases['import']['observation']['version'], '4.5.0.0')
        self.assertEqual(cases['generatorOption']['observation']['generatedTypes'], ['System.Runtime.CompilerServices.RequiresLocationAttribute'])
        for name, case in cases.items():
            expected = 0 if name in ('unchanged', 'relocated') else 1
            self.assertEqual(len([a for a in case['actions'] if not a['cacheHit']]), expected)
            if name not in ('unchanged', 'relocated'): self.assertTrue(case['preparationWorkspaceAbsent'])
            self.assertTrue((output / case['executionLog']).is_file())
        self.assertTrue(cases['relocated']['producerStateAbsentBeforeBuild'])
        self.assertEqual(cases['cold']['bundleFiles'], cases['relocated']['bundleFiles'])


if __name__ == '__main__': unittest.main()
