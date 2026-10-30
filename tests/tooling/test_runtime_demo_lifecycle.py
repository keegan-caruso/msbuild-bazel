"""Keep consumer recovery independent of a verified, retired producer VM."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/setup-runtime-demo.py'
spec = importlib.util.spec_from_file_location('runtime_demo_setup', SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ProducerLifecycle(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ['rules.tar', 'inputs.tar.gz', 'seed.json']:
            (self.root / name).write_text(name)
        (self.root / 'transfer.json').write_text(json.dumps(dict(inputsSha256=setup.digest(self.root / 'inputs.tar.gz'))))
        self.state = dict(id='owned', producer='producer', image='image@sha256:abcd', ready=True,
            completed=['transfer'], rulesSha256=setup.digest(self.root / 'rules.tar'))
        self.row = dict(configuration=dict(labels={'rules-msbuild.demo': 'owned'},
            image=dict(descriptor=dict(digest='sha256:abcd'))), status=dict(state='stopped'))
        self.inspect = patch.object(setup, 'inspect', return_value=self.row).start()
        self.call = patch.object(setup, 'call').start()
        self.addCleanup(patch.stopall)

    def test_archive_persists_proof_before_delete_and_supports_missing_producer(self):
        def deleted(*command):
            saved = json.loads((self.root / 'setup.json').read_text())
            self.assertEqual(saved['producerArchive']['seedSha256'], setup.digest(self.root / 'seed.json'))
        self.call.side_effect = deleted
        setup.archive_producer(self.root, self.state)
        self.call.assert_called_once_with('container', 'delete', 'producer')
        self.inspect.return_value = None
        self.assertIsNone(setup.verify_producer(self.root, self.state))
        setup.archive_producer(self.root, self.state)
        self.assertEqual(self.call.call_count, 1)

    def test_live_producer_never_deleted(self):
        self.row['status']['state'] = 'running'
        with self.assertRaisesRegex(AssertionError, 'Stop this setup'):
            setup.archive_producer(self.root, self.state)
        self.call.assert_not_called()

    def test_foreign_producer_never_deleted(self):
        self.row['configuration']['labels']['rules-msbuild.demo'] = 'someone-else'
        with self.assertRaisesRegex(AssertionError, 'ownership'):
            setup.archive_producer(self.root, self.state)
        self.call.assert_not_called()

    def test_missing_producer_without_proof_rejected(self):
        self.inspect.return_value = None
        with self.assertRaisesRegex(AssertionError, 'without a verified archive'):
            setup.verify_producer(self.root, self.state)

    def test_changed_retained_inputs_rejected_after_deletion(self):
        setup.archive_producer(self.root, self.state)
        self.inspect.return_value = None
        for name in ['rules.tar', 'inputs.tar.gz', 'seed.json']:
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(b'changed')
                with self.assertRaises(AssertionError):
                    setup.verify_producer(self.root, self.state)
                path.write_bytes(original)

    def test_unverified_checkpoint_never_deleted(self):
        (self.root / 'inputs.tar.gz').write_bytes(b'changed')
        with self.assertRaisesRegex(AssertionError, 'checkpoint changed'):
            setup.archive_producer(self.root, self.state)
        self.call.assert_not_called()

    def test_failed_delete_can_resume_from_persisted_proof(self):
        self.call.side_effect = RuntimeError('interrupted deletion')
        with self.assertRaises(RuntimeError):
            setup.archive_producer(self.root, self.state)
        saved = json.loads((self.root / 'setup.json').read_text())
        self.inspect.return_value = None
        self.assertIsNone(setup.verify_producer(self.root, saved))


if __name__ == '__main__':
    unittest.main()
