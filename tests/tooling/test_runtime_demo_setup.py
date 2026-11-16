"""Check that demo handoffs transfer declared inputs and reject unsafe checkpoints."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_build/upstream'))
import runtime_demo_prepare as demo
from runtime_demo_prepare import AUXILIARY, digest, pack, unpack


class RuntimeDemoInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'producer'
        self.root.mkdir()
        nodes = [dict(Inputs=['Source.cs'], OutputDirectories=['out/' + str(i)] if i < 481 else []) for i in range(543)]
        contract = dict(Projects={'App.csproj': dict(Configurations=nodes)}, SharedInputs=[], DefinitionDigests={}, Restore=dict(Inputs=[]))
        for name, body in {'Source.cs':'public class C {}', 'BUILD.bazel':'', 'MODULE.bazel.lock':'{}',
            'graph.generated.bzl':'', 'nuget.lock.json':'{}', 'mappings.json':'{}', 'application.json':'{}', 'runtime_test_settings.bzl':'',
            'graph.generated.json':json.dumps(contract), 'suite.json':json.dumps(dict(tests=[{}]*8)),
            'MODULE.bazel':'local_path_override(module_name="rules_msbuild",path="/old/rules")\n'}.items():
            (self.root/name).write_text(body)
        for folder in AUXILIARY:
            (self.root/folder).mkdir()
        native = self.root/'native/source.tar'
        native.write_bytes(b'declared archive')
        os.link(native, self.root/'host/source.tar')
        executable = self.root/'suite-host/host.sh'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        outputs = self.root/'out/0'
        outputs.mkdir(parents=True)
        (outputs/'App.dll').write_bytes(b'not an input')
        (self.root/'bazel-bin').symlink_to(outputs, target_is_directory=True)
        self.archive = self.base/'inputs.tar.gz'

    def test_read_only_cache_probe_accepts_missing_entry_without_put(self):
        missing = urllib.error.HTTPError('http://cache/cas/probe', 404, 'missing', {}, io.BytesIO())
        with patch.object(demo.urllib.request, 'urlopen', side_effect=missing) as request:
            demo.probe_cache('http://cache', '1')
            self.assertEqual(request.call_count, 1)
            self.assertIsInstance(request.call_args.args[0], str)

    def test_read_only_cache_probe_verifies_present_bytes(self):
        for body, valid in [(b'rules-msbuild-runtime-demo-cache-probe', True), (b'corrupt', False)]:
            with self.subTest(valid=valid):
                response = io.BytesIO(body); response.status = 200
                with patch.object(demo.urllib.request, 'urlopen', return_value=response) as request:
                    if valid:
                        demo.probe_cache('http://cache', '1')
                    else:
                        with self.assertRaisesRegex(AssertionError, 'bytes differ'):
                            demo.probe_cache('http://cache', '1')
                    self.assertEqual(request.call_count, 1)
                    self.assertIsInstance(request.call_args.args[0], str)
        denied = urllib.error.HTTPError('http://cache/cas/probe', 403, 'denied', {}, io.BytesIO())
        with patch.object(demo.urllib.request, 'urlopen', side_effect=denied):
            with self.assertRaises(urllib.error.HTTPError):
                demo.probe_cache('http://cache', '1')

    def test_default_cache_probe_keeps_put_then_get(self):
        uploaded = io.BytesIO(); uploaded.status = 204
        downloaded = io.BytesIO(b'rules-msbuild-runtime-demo-cache-probe'); downloaded.status = 200
        with patch.object(demo.urllib.request, 'urlopen', side_effect=[uploaded, downloaded]) as request:
            demo.probe_cache('http://cache')
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args_list[0].args[0].get_method(), 'PUT')
            self.assertIsInstance(request.call_args_list[1].args[0], str)

    def test_demo_guest_injects_saved_policy_into_nested_bazel(self):
        binary = self.root/'.tools/bin/bazelisk'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        binary.chmod(0o755)
        with patch.object(demo, 'ROOT', self.root), patch.object(demo, 'BASE', self.base), patch.dict(os.environ):
            os.environ.pop('RULES_MSBUILD_PROJECT_CACHE_READ_ONLY', None)
            demo.configure_project_cache({'projectCacheReadOnly': '1'})
            wrapper = os.environ['RULES_MSBUILD_BAZELISK']
            args = subprocess.check_output([wrapper, 'build', '//:app'], text=True).splitlines()
            self.assertIn('--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1', args)
            self.assertEqual(os.environ['RULES_MSBUILD_PROJECT_CACHE_READ_ONLY'], '1')
            self.assertFalse(any(arg.startswith('--remote_upload_local_results') for arg in args))

    @unittest.skipUnless(hasattr(tarfile, 'data_filter'), 'Secure extraction requires the qualified Linux Python runtime')
    def test_round_trip_preserves_inputs_hardlinks_modes_and_rebases_rules(self):
        (self.root/'Source.cs').chmod(0o664)
        (self.root/'native/source.tar').chmod(0o660)
        expected = pack(self.root, self.archive)
        consumer = unpack(self.archive, expected, self.base/'consumer')
        self.assertEqual((consumer/'Source.cs').read_bytes(), (self.root/'Source.cs').read_bytes())
        self.assertEqual((consumer/'Source.cs').stat().st_mode & 0o777, 0o664)
        self.assertEqual((consumer/'native/source.tar').stat().st_mode & 0o777, 0o660)
        self.assertTrue((consumer/'suite-host/host.sh').stat().st_mode & 0o111)
        self.assertEqual((consumer/'native/source.tar').stat().st_ino, (consumer/'host/source.tar').stat().st_ino)
        self.assertNotIn('/old/rules', (consumer/'MODULE.bazel').read_text())
        self.assertFalse((consumer/'bazel-bin').exists())
        self.assertFalse((consumer/'out').exists())

    @unittest.skipUnless(hasattr(tarfile, 'data_filter'), 'Secure extraction requires the qualified Linux Python runtime')
    def test_input_modes_are_manifest_checked_and_special_bits_stripped(self):
        pack(self.root, self.archive)
        for special in (False, True):
            with self.subTest(special=special):
                altered = self.base/('mode-' + str(special) + '.tar.gz')
                with tarfile.open(self.archive) as source, tarfile.open(altered, 'w:gz') as output:
                    for member in source:
                        if member.name == 'workspace/Source.cs':
                            member.mode = (member.mode | 0o7000) if special else (member.mode ^ 0o020)
                        output.addfile(member, source.extractfile(member) if member.isfile() else None)
                destination = self.base/('mode-consumer-' + str(special))
                if special:
                    consumer = unpack(altered, digest(altered), destination)
                    self.assertEqual((consumer/'Source.cs').stat().st_mode & 0o7777,
                                     (self.root/'Source.cs').stat().st_mode & 0o777)
                else:
                    with self.assertRaisesRegex(AssertionError, 'Source.cs'):
                        unpack(altered, digest(altered), destination)

    def test_wrong_archive_digest_rejected_before_extraction(self):
        pack(self.root, self.archive)
        with self.assertRaises(AssertionError):
            unpack(self.archive, '0'*64, self.base/'consumer')
        self.assertFalse((self.base/'consumer').exists())

    def test_declared_symlink_rejected(self):
        source = self.root/'Source.cs'
        source.unlink()
        source.symlink_to(self.base/'outside.cs')
        (self.base/'outside.cs').write_text('outside')
        with self.assertRaises(AssertionError):
            pack(self.root, self.archive)

    def test_auxiliary_build_outputs_rejected(self):
        folder = self.root/'app/bin'
        folder.mkdir()
        (folder/'App.dll').write_bytes(b'warm output')
        with self.assertRaisesRegex(AssertionError, 'Generated auxiliary output'):
            pack(self.root, self.archive)

    def test_traversal_and_symlink_members_rejected(self):
        for name, symlink in [('../escaped', False), ('workspace/link', True)]:
            with tarfile.open(self.archive, 'w:gz') as output:
                member = tarfile.TarInfo(name)
                if symlink:
                    member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
                    output.addfile(member)
                else:
                    member.size = 1
                    output.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(AssertionError):
                unpack(self.archive, digest(self.archive), self.base/('symlink' if symlink else 'traversal'))
        self.assertFalse((self.base/'escaped').exists())

    @unittest.skipUnless(hasattr(tarfile, 'data_filter'), 'Secure extraction requires the qualified Linux Python runtime')
    def test_inner_digest_rejects_modified_input(self):
        pack(self.root, self.archive)
        altered = self.base/'altered.tar.gz'
        with tarfile.open(self.archive) as source, tarfile.open(altered, 'w:gz') as output:
            for member in source:
                if member.name == 'workspace/Source.cs':
                    payload = b'changed'
                    member.size = len(payload)
                    output.addfile(member, io.BytesIO(payload))
                else:
                    output.addfile(member, source.extractfile(member) if member.isfile() else None)
        with self.assertRaises(AssertionError):
            unpack(altered, digest(altered), self.base/'consumer')


if __name__ == '__main__':
    unittest.main()
