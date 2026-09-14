from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import preparation_reuse as reuse
from preparation_identity import IdentityError


class ReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.state = self.root / 'state'
        self.entries = [dict(project='App.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})]

    def test_unowned_state_is_not_deleted(self):
        self.state.mkdir()
        sentinel = self.state / 'important'
        sentinel.write_text('keep')
        with patch.object(reuse.prepare_graph, 'DOTNET_ROOT', reuse.discovery.SDK):
            with self.assertRaisesRegex(IdentityError, 'not owned'):
                with reuse.prepared_view(self.source, self.state, self.root / 'out', self.entries): pass
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_overlapping_paths_reject_before_mutation(self):
        for state, output in ((self.source / 'state', self.root / 'out'),
                              (self.state, self.state / 'output'),
                              (self.state, self.source / 'output')):
            with self.subTest(state=state, output=output), self.assertRaises(IdentityError):
                with reuse.prepared_view(self.source, state, output, self.entries): pass
        self.assertEqual(list(self.source.iterdir()), [])

    def test_tests_environment_and_configuration_use_fresh_path(self):
        @contextmanager
        def fresh(*args, **kwargs):
            yield dict(reused=False, request=kwargs)
        for extra in ({'tests': []}, {'environment': {}}, {}):
            entries = self.entries if extra else [dict(project='App.csproj', globalProperties={'Configuration': 'Debug'})]
            with patch.object(reuse, 'fresh_view', side_effect=fresh) as called:
                with reuse.prepared_view(self.source, self.state, self.root / 'out', entries, **extra) as result:
                    self.assertFalse(result['reused'])
                called.assert_called_once()
                self.assertFalse(self.state.exists())

    def test_invalid_generation_cannot_escape_state(self):
        self.state.mkdir()
        for name in ('../source', '/tmp', None, 'z' * 32):
            (self.state / 'current.json').write_text(json.dumps(dict(generation=name)))
            candidate, reason = reuse.read_candidate(self.state, {})
            self.assertIsNone(candidate)
            self.assertIn('missing-or-corrupt', reason)

    def test_payload_identity_covers_mode_content_membership_and_relocation(self):
        import shutil
        payload = self.root / 'payload'
        payload.mkdir()
        (payload / 'file').write_text('one')
        baseline = reuse.payload_identity(payload)
        copied = self.root / 'copied'
        shutil.copytree(payload, copied)
        self.assertEqual(reuse.payload_identity(copied), baseline)
        (payload / 'file').chmod(0o700)
        self.assertNotEqual(reuse.payload_identity(payload), baseline)
        (copied / 'file').write_text('two')
        self.assertNotEqual(reuse.payload_identity(copied), baseline)
        (copied / 'link').symlink_to('file')
        with self.assertRaisesRegex(IdentityError, 'symlinks'): reuse.payload_identity(copied)

    def test_failed_atomic_switch_preserves_previous_pointer(self):
        pointer = self.root / 'current.json'
        reuse.atomic_json(pointer, dict(generation='old'))
        with patch('preparation_reuse.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): reuse.atomic_json(pointer, dict(generation='new'))
        self.assertEqual(json.loads(pointer.read_text()), dict(generation='old'))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['current.json', 'source'])

    def test_consumer_error_is_not_retried_as_fresh_preparation(self):
        @contextmanager
        def qualified(*args, **kwargs): yield {'certificate': True}
        generation = self.root / 'generation'
        (generation / 'payload').mkdir(parents=True)
        (generation / 'payload/file').write_text('value')
        (generation / 'manifest.json').write_text(json.dumps(dict(payloadSha256=reuse.payload_identity(generation / 'payload'))))
        with patch.object(reuse.prepare_graph, 'DOTNET_ROOT', reuse.discovery.SDK), \
             patch.object(reuse, 'tool_identity', return_value={}), \
             patch.object(reuse.discovery, 'qualified_view', side_effect=qualified), \
             patch.object(reuse, 'publish', return_value=generation), \
             patch.object(reuse, 'fresh_view') as fresh:
            with self.assertRaisesRegex(ValueError, 'consumer failed'):
                with reuse.prepared_view(self.source, self.state, self.root / 'out', self.entries):
                    raise ValueError('consumer failed')
            fresh.assert_not_called()

    def test_changed_leased_view_rejects_before_publication(self):
        from preparation_identity import tree_snapshot
        (self.source / 'file').write_text('original')
        snapshot = tree_snapshot(self.source)
        certificate = dict(identity=dict(roots={'workspace': dict(location=str(self.source), sha256=snapshot['sha256'])}), externalAbsent=[])
        reuse.verify_view(certificate)
        (self.source / 'file').write_text('changed')
        with self.assertRaisesRegex(IdentityError, 'before publication'):
            reuse.verify_view(certificate)

    def test_payload_changed_after_candidate_validation_is_not_exposed(self):
        generation = self.root / 'generation'
        (generation / 'payload').mkdir(parents=True)
        (generation / 'payload/file').write_text('original')
        manifest = dict(certificate={}, payloadSha256=reuse.payload_identity(generation / 'payload'))
        @contextmanager
        def qualified(*args, **kwargs):
            (generation / 'payload/file').write_text('corrupt')
            yield dict(unchanged=True)
        with patch.object(reuse.prepare_graph, 'DOTNET_ROOT', reuse.discovery.SDK), \
             patch.object(reuse, 'tool_identity', return_value={}), \
             patch.object(reuse, 'read_candidate', return_value=((generation, manifest), None)), \
             patch.object(reuse.discovery, 'qualified_view', side_effect=qualified):
            with self.assertRaisesRegex(IdentityError, 'payload changed during copy'):
                with reuse.prepared_view(self.source, self.state, self.root / 'out', self.entries): pass
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__': unittest.main()
