"""Check configured graph edges before writing any Bazel actions."""
import tarfile
import tempfile
import unittest
from pathlib import Path

from component_graph_prepare import expanded_sdk_graph, script, selected_nodes, validate_native_archive


class ComponentGraphTests(unittest.TestCase):
    def graph(self):
        return {
            'sourceRevision': 'revision',
            'globalProperties': {
                'DotNetBuildSourceOnly': 'true',
                'DotNetBuildSharedComponents': 'true',
                'Configuration': 'Release',
                'TargetArchitecture': 'arm64',
            },
            'sdkDependencyOrder': ['base', 'tool', 'independent', 'app'],
            'nodes': {
                'base': {'Items': {'RepositoryReference': [], 'BuiltSdkPackage': []}},
                'tool': {'Items': {'RepositoryReference': [
                    {'Identity': 'base'}, {'Identity': 'app', 'BuildReference': 'false'},
                ], 'BuiltSdkPackage': [{'Identity': 'Microsoft.Build.NoTargets'}]}},
                'independent': {'Items': {'RepositoryReference': [{'Identity': 'base'}], 'BuiltSdkPackage': []}},
                'app': {'Items': {'RepositoryReference': [{'Identity': 'tool'}], 'BuiltSdkPackage': []}},
            },
        }

    def test_evaluated_conditions_and_edges(self):
        self.assertEqual(selected_nodes(self.graph(), 'app', 'revision'),
                         {'base': [], 'tool': ['base'], 'app': ['tool']})
        self.assertEqual(selected_nodes(self.graph(), 'independent', 'revision'),
                         {'base': [], 'independent': ['base']})

    def test_rejects_drift_and_missing_dependencies(self):
        graph = self.graph()
        with self.assertRaisesRegex(ValueError, 'revision'):
            selected_nodes(graph, 'app', 'other')
        graph['nodes']['tool']['Items']['RepositoryReference'][0]['Identity'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'missing or out of order'):
            selected_nodes(graph, 'app', 'revision')

    def test_private_native_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / 'native.tar'
            with tarfile.open(archive, 'w') as output:
                output.addfile(tarfile.TarInfo('etc/ssl/private'))
            with self.assertRaisesRegex(ValueError, 'private host material'):
                validate_native_archive(archive)

    def test_built_sdk_layout_is_declared_from_evaluated_item(self):
        command = script('tool', ['base'], ['Microsoft.Build.NoTargets'])
        self.assertIn('--extra-tree artifacts/source-built-sdks/Microsoft.Build.NoTargets', command)
        with self.assertRaisesRegex(ValueError, 'Invalid built SDK'):
            script('tool', [], ['../outside'])

    def test_only_new_sdk_items_allow_graph_migration(self):
        current = self.graph()
        previous = self.graph()
        for node in previous['nodes'].values():
            del node['Items']['BuiltSdkPackage']
        self.assertTrue(expanded_sdk_graph(previous, current))
        previous['sdkDependencyOrder'].reverse()
        self.assertFalse(expanded_sdk_graph(previous, current))


if __name__ == '__main__':
    unittest.main()
