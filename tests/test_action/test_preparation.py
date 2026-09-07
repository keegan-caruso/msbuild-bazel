"""Explicit data publication rejects undeclared paths before any test can run."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from prepare_graph_tests import add_tests


class PreparationTests(unittest.TestCase):
    def exercise(self, data, expected=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / 'workspace'; workspace.mkdir()
            (workspace / 'approved.txt').write_text('approved')
            (root / 'outside.txt').write_text('outside')
            (workspace / 'escape.txt').symlink_to(root / 'outside.txt')
            output = root / 'output'; output.mkdir()
            (root / 'bazel').mkdir(); (root / 'bazel/graph_test.bzl').write_text('rule')
            runner = root / 'tools/TestRunner/bin/Release/net10.0'; runner.mkdir(parents=True)
            for suffix in ('.dll', '.deps.json', '.runtimeconfig.json'):
                (runner / ('TestRunner' + suffix)).write_text('fixture')
            node = dict(project='workspace/test/Test.csproj', globalProperties={'targetframework': 'net10.0'},
                        execution={'outputDirectory': 'workspace/test/bin/Release/net10.0'},
                        outputs=[{'kind':'assembly', 'path': 'workspace/test/bin/Release/net10.0/Test.dll'}])
            declaration = add_tests(workspace, output, {'n': node},
                                    [dict(node='n', data=data, expectedTests=expected if expected is not None else ['One.Fact'])], root)
            return declaration, json.loads((output / 'tests.json').read_text())

    def test_declared_data_published_with_content_hash(self):
        declaration, manifest = self.exercise(['approved.txt'])
        self.assertIn('assembly = "Test.dll"', declaration)
        self.assertEqual(manifest['tests'][0]['dataHashes'], {'approved.txt': '2687f86ed6784b8a5fca36e6c468e12aa44dc3c7e8137e3160d1a95079bdcd02'})

    def test_unsafe_missing_duplicate_or_escaping_data_rejected(self):
        for data in (['../outside.txt'], ['missing.txt'], ['escape.txt'], ['approved.txt', 'approved.txt']):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.exercise(data)

    def test_empty_or_duplicate_expected_names_rejected(self):
        for expected in ([], ['One.Fact', 'One.Fact']):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                self.exercise([], expected)
