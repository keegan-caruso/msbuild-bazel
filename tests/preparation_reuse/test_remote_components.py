import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import remote_components as components
import remote_preparation as remote
from preparation_identity import IdentityError
from portable_cache import sha
from remote_packages import archive
from probe_http_cache import CacheServer


class ComponentTests(unittest.TestCase):
    def test_reuse_edit_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp, CacheServer() as server:
            root = Path(temp); source = root / 'source'; source.mkdir()
            (source / 'src/A').mkdir(parents=True); (source / 'src/B').mkdir()
            (source / 'src/A/A.cs').write_text('class A {}')
            (source / 'src/B/B.cs').write_text('class B {}')
            (source / 'graph.json').write_text('{}')
            endpoint = server.url + '/native'
            first = components.describe(source, set(), endpoint)
            start = len(server.events)
            self.assertEqual(first, components.describe(source, set(), endpoint))
            self.assertEqual(server.totals(start)['uploadBytes'], 0)
            (source / 'src/A/A.cs').write_text('class A { int x; }')
            second = components.describe(source, set(), endpoint)
            self.assertEqual(len({r['blob'] for r in first} & {r['blob'] for r in second}), 2)
            components.validate(second, set(), 10000)
            components.restore(endpoint, second, root / 'restored')
            self.assertEqual((root / 'restored/src/A/A.cs').read_bytes(), (source / 'src/A/A.cs').read_bytes())
            server.data['/native/cas/' + second[0]['blob']] = b'bad'
            with self.assertRaisesRegex(IdentityError, 'digest'): components.restore(endpoint, second, root / 'corrupt')

    def test_limits_and_overlaps(self):
        record = dict(blob='a'*64, files=[dict(path='src/a', size=2, sha256='b'*64, mode=420)])
        for records, occupied, limit in [([record, record], set(), 20), ([record], {'payload/src/a'}, 20), ([record], set(), 1), ([record], {'payload/src/a/child'}, 20)]:
            with self.assertRaises(IdentityError): components.validate(records, occupied, limit)

    def test_missing_incomplete_and_wrong_file_objects_reject(self):
        with tempfile.TemporaryDirectory() as temp, CacheServer() as server:
            endpoint = server.url + '/native'; root = Path(temp)
            item = dict(path='src/a', size=4, sha256=sha(b'good'), mode=420)
            record = dict(blob='a'*64, files=[item])
            from urllib.error import HTTPError
            with self.assertRaises(HTTPError): components.restore(endpoint, [record], root / 'missing')
            for label, files, message in [('incomplete', {}, 'incomplete'), ('wrong', {'src/a': b'evil'}, 'file mismatch'), ('extra', {'../escape': b'evil'}, 'member')]:
                data = archive(files); record['blob'] = sha(data)
                server.data['/native/cas/' + record['blob']] = data
                with self.assertRaisesRegex(IdentityError, message): components.restore(endpoint, [record], root / label)
            self.assertFalse((root / 'escape').exists())

    def test_evidence_roundtrip_reuse_and_corruption(self):
        original = dict(certificate={'identity': {'snapshots': {
            'workspace': {'entries': []}, 'runtime-0': {'entries': [{'path': 'sdk'}]},
            'GraphExport': {'entries': [{'path': 'tool'}]}}}})
        with CacheServer() as server:
            endpoint = server.url + '/native'
            metadata = copy.deepcopy(original)
            remote.split_evidence(metadata, endpoint)
            blob = metadata['evidence']
            start = len(server.events)
            again = copy.deepcopy(original); remote.split_evidence(again, endpoint)
            self.assertEqual(server.totals(start)['uploadBytes'], 0)
            remote.hydrate_evidence(metadata, endpoint)
            self.assertEqual(metadata, original)
            server.data['/native/cas/' + blob] = b'corrupt'
            with self.assertRaisesRegex(IdentityError, 'digest'): remote.hydrate_evidence(again, endpoint)
