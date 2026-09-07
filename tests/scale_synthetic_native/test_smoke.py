"""Opt-in native ten-node correctness smoke; larger scales are separate experiments."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SyntheticNative(unittest.TestCase):
    def test_ten_node_fan_fresh_and_warm(self):
        output = Path(tempfile.mkdtemp(prefix='synthetic-scale-')) / 'probe'
        print('Synthetic scale evidence: ' + str(output), flush=True)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_synthetic_scale.py'),
            '--nodes', '10', '--shape', 'fan', '--cases', 'fresh', 'warm', '--output', str(output)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads((output / 'report.json').read_text())
        self.assertFalse(report['performanceQualified'])
        self.assertIsNone(report['budgets'])
        for case, count in (('fresh', 10), ('warm', 0)):
            record = report['cases'][case]
            self.assertEqual(record['nodeCount'], 10)
            self.assertEqual(record['edgeCount'], 13)
            self.assertEqual(record['output'], '70')
            self.assertEqual(record['ordinaryOutput'], '70')
            self.assertEqual(record['ordinaryCompilerInvocations'], count)
            self.assertEqual(len([a for a in record['actions'] if not a['cacheHit']]), count)
            self.assertTrue(record['preparationWorkspaceAbsent'])
            self.assertTrue((output / record['executionLog']).is_file())
        self.assertTrue(all(p['processTreePeakBytes'] is None for p in report['phases'].values()))


if __name__ == '__main__': unittest.main()
