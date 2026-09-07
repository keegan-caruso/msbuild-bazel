"""Actual downstream selected-inner action identity and transitive replay."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_graph_execution import probe

class SelectedFrameworkNative(unittest.TestCase):
    def test_multitargeted_dependency_retains_sdk_selection(self):
        output = Path(tempfile.mkdtemp(prefix='selected-framework-native-'))/'probe'
        report = probe(output, selected_reference=True)
        self.assertEqual(report['output'], 'shared-v1:left|shared-v1:right')
        self.assertEqual(report['output'], report['baselineOutput'])
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(len(report['executedProjects']), 4)
        for project, action in report['actions'].items():
            self.assertFalse(action['cacheHit'])
            self.assertIn(action['runner'], ('darwin-sandbox', 'linux-sandbox'))
            self.assertEqual(action['compiledProjects'], [Path(project).stem])
        self.assertEqual(set(report['actions']['src/App/App.csproj']['replayHits']), {'Shared','Left','Right'})
        manifest = json.loads((output/'manifest.json').read_text())
        shared = next(n for n in manifest['nodes'] if n['project'].endswith('/Shared.csproj'))
        self.assertEqual(shared['globalProperties']['targetframework'], 'net10.0')
        project = output/'workspace/src/src/Shared/Shared.csproj'
        self.assertIn('<TargetFrameworks>net10.0;netstandard2.1</TargetFrameworks>', project.read_text())
        print('Selected framework native evidence: '+str(output), flush=True)
