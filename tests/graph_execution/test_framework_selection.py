"""Declared selected edges cannot collapse conflicting configured frameworks."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from prepare_graph import framework_selections

class FrameworkSelection(unittest.TestCase):
    def node(self, project, deps=(), framework='net10.0'):
        return dict(project='workspace/'+project, dependencies=list(deps), targetFramework=framework)

    def test_selected_reference_and_converged_identity(self):
        nodes = {'app':self.node('App.csproj', ['red','blue']),
                 'red':self.node('Shared.csproj'), 'blue':self.node('Shared.csproj')}
        nodes['app']['execution'] = dict(selectedReferences=[dict(project='workspace/Shared.csproj', targetFramework='net10.0')])
        result = framework_selections(nodes, nodes)
        self.assertEqual(result, {'App.csproj':dict(target_framework='net10.0', references={'Shared.csproj':'net10.0'}),
                                  'Shared.csproj':dict(target_framework='net10.0', references={})})

    def test_conflicting_framework_reference_rejected(self):
        nodes = {'app':self.node('App.csproj', ['red','blue']),
                 'red':self.node('Shared.csproj'), 'blue':self.node('Shared.csproj', framework='net9.0')}
        nodes['app']['execution'] = dict(selectedReferences=[dict(project='workspace/Shared.csproj', targetFramework='net10.0')])
        with self.assertRaisesRegex(ValueError, 'selected reference differs from dependency'):
            framework_selections(nodes, nodes)

    def test_conflicting_same_path_edges_rejected(self):
        nodes = {'red':self.node('Shared.csproj', ['dep']), 'blue':self.node('Shared.csproj'),
                 'dep':self.node('Common.csproj')}
        nodes['red']['execution'] = dict(selectedReferences=[dict(project='workspace/Common.csproj', targetFramework='net10.0')])
        with self.assertRaisesRegex(ValueError, 'conflicting selected framework edges'):
            framework_selections(nodes, nodes)
