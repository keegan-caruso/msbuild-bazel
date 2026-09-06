"""Milestone 2 black-box acceptance, committed before implementation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class GraphExecutionAcceptance(unittest.TestCase):
    def test_root_project_without_directory_build_imports(self):
        output = Path(tempfile.mkdtemp(prefix='graph-execution-')) / 'root'
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_graph_execution.py'), '--output', str(output), '--root-project'], text=True, capture_output=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + '\nEvidence: ' + str(output))
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['executedProjects'], ['App.csproj'])
        self.assertEqual(report['actions']['App.csproj']['compiledProjects'], ['App'])
        self.assertEqual(report['output'], 'root-project')
        self.assertEqual(report['output'], report['baselineOutput'])

    def test_native_sandbox_diamond_matches_baseline(self):
        probe = ROOT / 'tools/probe_graph_execution.py'
        self.assertTrue(probe.is_file(), 'Milestone 2 graph execution is not implemented')
        output = Path(tempfile.mkdtemp(prefix='graph-execution-')) / 'evidence'
        result = subprocess.run([sys.executable, str(probe), '--output', str(output)], text=True, capture_output=True, timeout=600)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + '\nEvidence: ' + str(output))
        report = json.loads((output / 'report.json').read_text())
        projects = {f'src/{name}/{name}.csproj' for name in ('Shared', 'Left', 'Right', 'App')}
        self.assertEqual(set(report['nodes'].values()), projects)
        self.assertEqual(sorted(report['executedProjects']), sorted(projects))
        self.assertEqual(report['output'], report['baselineOutput'])
        self.assertEqual(report['output'], 'shared-v1:left|shared-v1:right')
        for project, action in report['actions'].items():
            self.assertEqual(action['compiledProjects'], [Path(project).stem])
            self.assertIn(action['runner'], ('darwin-sandbox', 'linux-sandbox'))
        self.assertEqual(set(report['actions']['src/App/App.csproj']['replayHits']), {'Left', 'Right', 'Shared'})
        for name in ('Left', 'Right'):
            self.assertEqual(report['actions'][f'src/{name}/{name}.csproj']['replayHits'], ['Shared'])

if __name__ == '__main__':
    unittest.main()
