"""Black-box acceptance contract for public API replay."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MsbuildReplayTests(unittest.TestCase):
    def test_public_api_replay(self):
        directory = Path(tempfile.mkdtemp(prefix='msbuild-e2e-replay-')).resolve()
        try:
            process = subprocess.run([sys.executable, str(ROOT / 'tools/probe_replay.py'),
                                      '--output', str(directory / 'probe')],
                                     text=True, capture_output=True, timeout=900)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads((directory / 'probe/report.json').read_text())
            self.assertFalse((directory / 'probe/producer').exists())
            for name in ('samePath', 'relocated', 'appEdit', 'publish'):
                result = report['cases'][name]
                self.assertEqual(result['returncode'], 0, result)
                self.assertEqual(result['compiledProjects'], ['App'], result)
                self.assertEqual(result['replayHits'], ['Shared'], result)
                self.assertEqual(result['applicationReturncode'], 0, result)
                self.assertEqual(result['applicationOutput'],
                                 'shared-v1/app-v2' if name in ('appEdit', 'publish')
                                 else 'shared-v1/app-v1')
            for name in ('missingPayload', 'missingTarget', 'missingArtifact',
                         'propertiesMismatch', 'sdkMismatch', 'engineMismatch',
                         'schemaMismatch', 'externalPath', 'frameworkMismatch',
                         'rootMismatch', 'missingPublishTarget'):
                result = report['cases'][name]
                self.assertNotEqual(result['returncode'], 0, result)
                self.assertEqual(result['compiledProjects'], [], result)
                self.assertIn('dependency', Path(result['log']).read_text().lower())
        except BaseException:
            print(f'Retained replay workspace: {directory}', file=sys.stderr)
            raise
        else:
            shutil.rmtree(directory)
