import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from synthetic_graph import generate, topology, consumers, oracle, project


class SyntheticConstruction(unittest.TestCase):
    def test_sizes_topologies_and_complete_reachability(self):
        for count in (10, 100, 1000):
            for shape in ('chain', 'fan'):
                with self.subTest(count=count, shape=shape), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    first, second = directory / 'one', directory / 'two'
                    spec = generate(first, count, shape)
                    generate(second, count, shape)
                    self.assertEqual(len(list(first.rglob('*.csproj'))), count)
                    reachable = {count - 1}
                    for index in reversed(range(count)):
                        if index in reachable: reachable.update(spec['edges'][index])
                    self.assertEqual(reachable, set(range(count)))
                    for index, dependencies in enumerate(spec['edges']):
                        self.assertTrue(all(d < index for d in dependencies))
                    files = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                    self.assertEqual(files(first), files(second))
                    self.assertNotIn(str(first), json.dumps(spec))
                    self.assertEqual(consumers(spec['edges'], 0), set(range(count)))
                    self.assertEqual(consumers(spec['edges'], count - 1), {count - 1})
                    self.assertNotEqual(oracle(spec['edges']), oracle(spec['edges'], 0))
                    self.assertNotEqual(oracle(spec['edges']), oracle(spec['edges'], count - 1))

    def test_invalid_specification_rejected(self):
        for count, shape in ((0, 'chain'), (1, 'fan'), (10, 'unknown')):
            with self.assertRaises(ValueError): topology(count, shape)


if __name__ == '__main__': unittest.main()
