"""Check configured graph edges before writing any Bazel actions."""
import tarfile
import tempfile
import unittest
from pathlib import Path

from component_graph_prepare import selected_nodes, validate_native_archive


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
                'base': {'Items': {'RepositoryReference': []}},
                'tool': {'Items': {'RepositoryReference': [
                    {'Identity': 'base'}, {'Identity': 'app', 'BuildReference': 'false'},
                ]}},
                'independent': {'Items': {'RepositoryReference': [{'Identity': 'base'}]}},
                'app': {'Items': {'RepositoryReference': [{'Identity': 'tool'}]}},
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


if __name__ == '__main__':
    unittest.main()
