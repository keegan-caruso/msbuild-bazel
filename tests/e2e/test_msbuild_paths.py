"""Real MSBuild path probes, including a raw-cache negative control."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MsbuildPathTests(unittest.TestCase):
    def test_bundle_move_and_workspace_relocation(self):
        directory = Path(tempfile.mkdtemp(prefix='msbuild-e2e-paths-')).resolve()
        output = directory / 'probe'
        try:
            process = subprocess.run(
                [sys.executable, str(ROOT / 'tools/probe_paths.py'),
                 '--output', str(output)],
                cwd=ROOT, text=True, capture_output=True, timeout=900,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads((output / 'report.json').read_text())
            self.assertEqual(report['schemaVersion'], 1)
            self.assertFalse((output / 'producer-workspace').exists())
            self.assertFalse((output / 'original-bundle').exists())
            for scenario in ('movedBundle', 'freshCacheControl'):
                observed = report[scenario]
                log = Path(observed['log']).read_text()
                self.assertEqual(observed['returncode'], 0, scenario)
                self.assertIn('RULES_MSBUILD_COMPILE:App', log, scenario)
                self.assertNotIn('RULES_MSBUILD_COMPILE:Shared', log, scenario)
                self.assertEqual(observed['compiledProjects'], ['App'], scenario)
                self.assertEqual(observed['applicationReturncode'], 0, scenario)
                self.assertEqual(observed['applicationOutput'], 'shared-v1/app-v1', scenario)
            for bundle in ('different-action-output/shared-bundle', 'fresh-shared'):
                self.assertIn('RULES_MSBUILD_COMPILE:Shared', (output / bundle / 'build.log').read_text())
            relocated = report['relocatedWorkspace']
            self.assertNotEqual(relocated['returncode'], 0)
            self.assertEqual(relocated['compiledProjects'], [])
            log = Path(relocated['log']).read_text()
            self.assertNotIn('RULES_MSBUILD_COMPILE:', log)
            self.assertIn('MSB4252', log)
            self.assertIn('GetTargetFrameworks', log)
            self.assertIn(str(output / 'consumer-workspace/Shared/Shared.csproj'), log)
        except BaseException:
            print(f'Retained e2e workspace: {directory}', file=sys.stderr)
            raise
        else:
            shutil.rmtree(directory)


if __name__ == '__main__':
    unittest.main()
