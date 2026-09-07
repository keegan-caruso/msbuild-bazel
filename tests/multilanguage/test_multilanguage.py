"""Native upstream-rule composition acceptance; tools/download errors are failures."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class MultilanguageAcceptance(unittest.TestCase):
    def test_composition_and_language_local_edits(self):
        output = Path(tempfile.mkdtemp(prefix='msbuild-multilanguage-')) / 'probe'
        print('Multilanguage evidence: ' + str(output), file=sys.stderr)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_multilanguage.py'),
                                 '--output', str(output)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads((output / 'multilanguage-report.json').read_text())
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(set(report['cases']), {'polyglotCold', 'polyglotUnchanged',
                                              'pythonEdit', 'typescriptEdit', 'dotnetEdit',
                                              'recoveryBaseline', 'diskCache'})
