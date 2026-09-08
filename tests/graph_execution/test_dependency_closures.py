"""Graph reachability at discovery sizes, without compiler/tool acquisition."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_graph


class DependencyClosureTests(unittest.TestCase):
    def closures(self, edges):
        return prepare_graph.dependency_closures({node: {'dependencies': dependencies} for node, dependencies in edges.items()})

    def test_known_diamond_and_disconnected_node(self):
        self.assertEqual(self.closures({'app': ['left', 'right'], 'left': ['shared'], 'right': ['shared'], 'shared': [], 'unused': []}),
            {'shared': {'shared'}, 'left': {'left', 'shared'}, 'right': {'right', 'shared'},
             'app': {'app', 'left', 'right', 'shared'}, 'unused': {'unused'}})

    def test_thousand_node_chain_exact_closures(self):
        edges = {index: [index + 1] if index < 999 else [] for index in range(1000)}
        closures = self.closures(edges)
        for index in range(1000):
            self.assertEqual(closures[index], set(range(index, 1000)))

    def test_thousand_node_layered_fan_converges(self):
        # Repeated diamonds would revisit exponentially many paths in recursive DFS.
        edges = {index: list(range(max(0, index // 2 * 2 - 2), index // 2 * 2)) for index in range(1000)}
        closures = self.closures(edges)
        for index in range(1000):
            self.assertEqual(closures[index], set(range(index // 2 * 2)) | {index})

    def test_duplicate_edges_do_not_change_reachability(self):
        self.assertEqual(self.closures({'app': ['leaf', 'leaf'], 'leaf': []}), {'app': {'app', 'leaf'}, 'leaf': {'leaf'}})

    def test_cycles_and_self_loop_fail(self):
        for edges in ({'a': ['a']}, {'a': ['b'], 'b': ['a']}, {'leaf': [], 'a': ['b', 'leaf'], 'b': ['a']}):
            with self.subTest(edges=edges), self.assertRaisesRegex(ValueError, '^cyclic graph$'):
                self.closures(edges)

    def test_missing_dependency_fails(self):
        with self.assertRaisesRegex(ValueError, '^missing dependency node$'):
            self.closures({'a': ['missing']})

    def test_thousand_node_chain_reaches_discovery_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nodes = []
            for index in range(1000):
                project = f'P{index}/P{index}.csproj'
                nodes.append(dict(id=f'{index:024x}', project='workspace/' + project,
                    globalProperties={'configuration': 'Release'}, targetFramework='net10.0',
                    dependencies=[f'{index + 1:024x}'] if index < 999 else [], inputs=[],
                    outputs=[dict(kind='assembly', path=f'workspace/P{index}/bin/Release/net10.0/P{index}.dll')]))
            manifest = root / 'graph.json'
            manifest.write_text(json.dumps(dict(schemaVersion=1,
                toolchain=dict(sdkVersion='10.0.400', graphEngine='ProjectGraph', contractVersion=1),
                nodes=nodes, entryPoints=[nodes[0]['id']], graphInputs=[])))
            with patch.object(prepare_graph.graph_packages, 'package_plan'), patch.object(prepare_graph.subprocess, 'run') as process:
                with self.assertRaisesRegex(ValueError, 'graph discovery request missing'):
                    prepare_graph.prepare(root / 'source', manifest, root / 'generated')
            process.assert_not_called()
            self.assertFalse((root / 'generated').exists())


if __name__ == '__main__':
    unittest.main()
