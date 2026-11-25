"""Fail closed before fallback and keep recovery consumers read-only."""
import collections
import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

SOURCE = Path(__file__).resolve().parents[1] / 'graph_build/upstream/runtime_http_recovery.py'
spec = importlib.util.spec_from_file_location('runtime_http_recovery', SOURCE)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RuntimeHttpRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.server = recovery.Cache(self.root, 1024**2)
        self.server.RequestHandlerClass = recovery.RecoveryHandler
        self.server.misses, self.server.get_bytes, self.server.active = [], collections.Counter(), None
        self.server.phase = 'recover'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def test_cache_misses_stop_process_group_before_fallback(self):
        for method in ['GET', 'HEAD']:
            with self.subTest(method=method):
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                         start_new_session=True)
                self.server.active = child
                try:
                    request = urllib.request.Request(self.url + '/cas/' + '0' * 64, method=method)
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request)
                    self.assertEqual(caught.exception.code, 404)
                    self.assertEqual(child.wait(timeout=3), -signal.SIGTERM)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    self.server.active = None

    def test_payload_count_and_denied_put(self):
        payload = b'exact HTTP payload'
        digest = recovery.hashlib.sha256(payload).hexdigest()
        (self.root / 'cas').mkdir()
        artifact = self.root / 'cas' / digest
        artifact.write_bytes(payload)
        self.assertEqual(urllib.request.urlopen(self.url + '/cas/' + digest).read(), payload)
        self.assertEqual(self.server.get_bytes['recover'], len(payload))
        request = urllib.request.Request(self.url + '/cas/' + digest, data=b'overwrite', method='PUT')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(artifact.read_bytes(), payload)

    def test_copy_retains_authored_bazel_names_and_omits_only_root_links(self):
        source = self.root / 'workspace'
        (source / 'nested/bazel-authored').mkdir(parents=True)
        (source / 'nested/bazel-authored/Code.cs').write_text('source')
        (source / 'bazel-authored.txt').write_text('authored')
        (source / 'bazel-bin').symlink_to(self.root / 'unavailable-output')
        manifest = recovery.inputs(source)
        target = self.root / 'copy'
        recovery.copy_inputs(source, target, manifest)
        self.assertEqual((target / 'nested/bazel-authored/Code.cs').read_text(), 'source')
        self.assertEqual((target / 'bazel-authored.txt').read_text(), 'authored')
        self.assertFalse((target / 'bazel-bin').is_symlink())

    def test_recovery_allows_only_identical_declared_toolchain_unpack(self):
        producer, consumer = self.root / 'producer', self.root / 'consumer'
        for workspace in [producer, consumer]:
            tool = workspace / 'bazel-bin/native/tools.root/usr/bin/tool'
            tool.parent.mkdir(parents=True)
            tool.write_bytes(b'declared package bytes')
            tool.chmod(0o755)
        output = dict(path='bazel-out/k8-fastbuild/bin/native/tools.root/usr/bin/tool',
                      digest=dict(hash='verified-output-digest'))
        unpack = dict(mnemonic='MSBuildNativeToolchainPackages', targetLabel='//native:tools',
                      cacheHit=False, runner='processwrapper-sandbox', actualOutputs=[output])
        remote = [dict(mnemonic=name, cacheHit=True, runner='remote cache hit')
                  for name, count in [('RuntimeNative', 3), ('MSBuildGraph', 3),
                                      ('MSBuildGraphRestore', 1), ('RuntimeNativeVersions', 1)]
                  for _ in range(count)]
        result = recovery.validate_recovery(remote + [unpack], [unpack], producer, consumer)
        self.assertEqual(result['remoteHits'], 8)
        self.assertTrue(result['localPreparation']['matchesColdBytesModesLinks'])
        with self.assertRaisesRegex(ValueError, 'Unexpected local'):
            recovery.validate_recovery(remote + [unpack, dict(mnemonic='UnexpectedProducer')],
                                       [unpack], producer, consumer)
        (consumer / 'bazel-bin/native/tools.root/usr/bin/tool').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'bytes, modes or links'):
            recovery.validate_recovery(remote + [unpack], [unpack], producer, consumer)

    def test_input_manifest_rejects_outputs_and_links(self):
        workspace = self.root / 'workspace'
        workspace.mkdir()
        (workspace / 'Code.cs').write_text('source')
        self.assertIn('Code.cs', recovery.inputs(workspace))
        (workspace / 'output').symlink_to('Code.cs')
        with self.assertRaisesRegex(ValueError, 'links or outputs'):
            recovery.inputs(workspace)
        (workspace / 'output').unlink()
        (workspace / 'obj').mkdir()
        with self.assertRaisesRegex(ValueError, 'links or outputs'):
            recovery.inputs(workspace)


if __name__ == '__main__':
    unittest.main()
