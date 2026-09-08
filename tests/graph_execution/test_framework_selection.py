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
        self.assertEqual(result, {'App.csproj':dict(target_framework='net10.0', remove_framework_global=True, references={'Shared.csproj':'net10.0'}),
                                  'Shared.csproj':dict(target_framework='net10.0', remove_framework_global=True, references={})})

    def test_framework_reference_absent_from_configured_dependencies_rejected(self):
        nodes = {'app':self.node('App.csproj', ['red','blue']),
                 'red':self.node('Shared.csproj'), 'blue':self.node('Shared.csproj', framework='net9.0')}
        nodes['app']['execution'] = dict(selectedReferences=[dict(project='workspace/Shared.csproj', targetFramework='net8.0')])
        with self.assertRaisesRegex(ValueError, 'selected reference differs from dependency'):
            framework_selections(nodes, nodes)

    def test_same_project_frameworks_preserve_distinct_edges(self):
        nodes = {'app': self.node('App.csproj', ['net8', 'external']),
                 'external': self.node('External.csproj', ['standard'], framework='netstandard2.0'),
                 'net8': self.node('Shared.csproj', framework='net8.0'),
                 'standard': self.node('Shared.csproj', ['generator'], framework='netstandard2.0'),
                 'generator': self.node('Generator.csproj', framework='netstandard2.0')}
        nodes['app']['execution'] = dict(selectedReferences=[dict(project='workspace/Shared.csproj', targetFramework='net8.0')])
        nodes['external']['execution'] = dict(selectedReferences=[dict(project='workspace/Shared.csproj', targetFramework='netstandard2.0')])
        result = framework_selections(nodes, nodes)
        self.assertEqual(result['App.csproj']['references']['Shared.csproj'], 'net8.0')
        self.assertEqual(result['External.csproj']['references']['Shared.csproj'], 'netstandard2.0')
        self.assertEqual(result['Shared.csproj|net8.0']['target_framework'], 'net8.0')
        self.assertEqual(result['Shared.csproj|netstandard2.0']['target_framework'], 'netstandard2.0')

    def test_conflicting_same_path_edges_rejected(self):
        nodes = {'red':self.node('Shared.csproj', ['dep']), 'blue':self.node('Shared.csproj'),
                 'dep':self.node('Common.csproj')}
        nodes['red']['execution'] = dict(selectedReferences=[dict(project='workspace/Common.csproj', targetFramework='net10.0')])
        with self.assertRaisesRegex(ValueError, 'conflicting selected framework edges'):
            framework_selections(nodes, nodes)

    def test_explicit_parent_and_implicit_child_keep_different_global_identities(self):
        nodes = {'app': self.node('App.csproj', ['generator']),
                 'generator': self.node('Generator.csproj', framework='netstandard2.0')}
        nodes['app']['globalProperties'] = {'configuration': 'Release', 'targetframework': 'net10.0'}
        nodes['generator']['globalProperties'] = {'configuration': 'Release'}
        result = framework_selections(nodes, nodes)
        self.assertFalse(result['App.csproj']['remove_framework_global'])
        self.assertTrue(result['Generator.csproj']['remove_framework_global'])
        self.assertEqual(result['Generator.csproj']['target_framework'], 'netstandard2.0')

    def test_same_path_explicit_and_implicit_global_identity_cannot_collapse(self):
        nodes = {'explicit': self.node('Shared.csproj'), 'implicit': self.node('Shared.csproj')}
        nodes['explicit']['globalProperties'] = {'targetframework': 'net10.0'}
        nodes['implicit']['globalProperties'] = {}
        with self.assertRaisesRegex(ValueError, 'conflicting selected framework edges'):
            framework_selections(nodes, nodes)
