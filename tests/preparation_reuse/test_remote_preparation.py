"""Portable proofs retain restore, namespace, host and negative-input checks."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import remote_preparation as remote
import remote_snapshot
import discovery_contract as discovery
from preparation_identity import capture, compare, digest, IdentityError
from preparation_reuse import payload_identity, publish, fresh_view


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.entries = [dict(project='App.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})]
        self.facts = dict(platform='test', machine='arm64', osBuild='build', bootSession='one', cpuCount=4)
        self.request = dict(entries=self.entries, tools={'trees': {'/controller/GraphExport': 'abc'}}, nativeToolchain='a'*64)
        self.old = self.identity('old')
        self.current = self.identity('new')
        cert = dict(schemaVersion=1, policy=discovery.POLICY, eligible=True, reuseEnabled=False, operation='GraphExport',
            timestampEpoch=discovery.EPOCH, identity=self.old, externalAbsent=[str(self.root / 'old/Directory.Build.targets')],
            graphSha256=digest({}), observationSha256='b'*64)
        cert['sha256'] = digest(cert)
        self.metadata = dict(certificate=cert, host=self.facts, request=remote.portable_request(self.request),
            workspaceEntries=remote.portable_entries(self.root / 'old/workspace', self.old['snapshots']['workspace']))

    def identity(self, name, *, body='class App {}', assets=None, receipt='random', host=None):
        base = self.root / name
        workspace = base / 'workspace'
        (workspace / 'obj').mkdir(parents=True, exist_ok=True)
        (workspace / 'App.cs').write_text(body)
        (workspace / 'obj/project.assets.json').write_text(json.dumps(assets or {'project': str(workspace), 'version': 1}))
        (workspace / 'obj/project.nuget.cache').write_text(json.dumps(dict(success=True, dgSpecHash=receipt)))
        roots = {'workspace': workspace}
        for tool in ('GraphExport', 'EvaluationProbe'):
            roots[tool] = base / 'tools' / tool
            roots[tool].mkdir(parents=True, exist_ok=True)
            (roots[tool] / 'tool.dll').write_bytes(b'tool')
        profile = discovery.sandbox_profile(list(roots.values()) + [base / 'output'], base / 'output')
        request = dict(policy=discovery.POLICY, timestampEpoch=discovery.EPOCH, entries=self.entries,
            sandboxSha256=digest(profile), contractSha256=discovery.CONTROLLER_DIGEST)
        return capture(roots, request=request, environment=discovery.controlled_environment(base / 'output'), host=host or self.facts)

    def test_equivalent_restore_paths_and_receipt_relocate(self):
        current = self.identity('new', receipt='different')
        rebased = remote.rebase(self.metadata, current, self.facts)
        self.assertTrue(compare(rebased['identity'], current)['unchanged'])
        self.assertEqual(rebased['externalAbsent'], [str(self.root / 'new/Directory.Build.targets')])

    def test_body_change_remains_visible_for_guarded_refresh(self):
        current = self.identity('new', body='class App { int Value() => 2; }')
        previous = remote.rebase(self.metadata, current, self.facts)
        self.assertEqual(compare(previous['identity'], current)['changedDomains'], ['root:workspace'])

    def test_assets_change_rejects(self):
        current = self.identity('new', assets={'version': 2})
        with self.assertRaisesRegex(IdentityError, 'restore inputs changed'): remote.rebase(self.metadata, current, self.facts)

    def test_namespace_change_rejects(self):
        (self.root / 'new/workspace/New.cs').write_text('class New {}')
        current = self.identity('new')
        with self.assertRaisesRegex(IdentityError, 'namespace'): remote.rebase(self.metadata, current, self.facts)

    def test_new_ancestor_input_rejects(self):
        (self.root / 'new/Directory.Build.targets').write_text('<Project/>')
        with self.assertRaisesRegex(IdentityError, 'external input exists'): remote.rebase(self.metadata, self.current, self.facts)

    def test_host_compatibility_excludes_only_boot_session(self):
        facts = dict(self.facts, bootSession='two')
        current = self.identity('new', host=facts)
        self.assertTrue(compare(remote.rebase(self.metadata, current, facts)['identity'], current)['unchanged'])
        facts['osBuild'] = 'different'
        current = self.identity('new', host=facts)
        with self.assertRaisesRegex(IdentityError, 'incompatible preparation host'): remote.rebase(self.metadata, current, facts)

    def test_invocation_mismatch_rejects(self):
        current = copy.deepcopy(self.current); current['environmentSha256'] = 'f'*64
        with self.assertRaisesRegex(IdentityError, 'invocation mismatch'): remote.rebase(self.metadata, current, self.facts)

    def generation(self):
        generation = self.root / 'generation'; payload = generation / 'payload'
        (payload / 'empty').mkdir(parents=True)
        (payload / 'graph.json').write_text('{}')
        (payload / 'program').write_bytes(b'program'); (payload / 'program').chmod(0o755)
        (generation / 'manifest.json').write_text(json.dumps(dict(request=self.request,
            certificate=self.metadata['certificate'], payloadSha256=payload_identity(payload))))
        return generation

    def test_deterministic_roundtrip_preserves_directories_and_modes(self):
        generation = self.generation()
        with patch.object(remote, 'host', return_value=self.facts):
            data = remote.pack(generation)
            self.assertEqual(data, remote.pack(generation))
        metadata = remote.unpack(data, self.root / 'imported', self.request)
        self.assertEqual(payload_identity(self.root / 'imported/payload'), metadata['payloadSha256'])
        self.assertTrue((self.root / 'imported/payload/empty').is_dir())
        with self.assertRaisesRegex(IdentityError, 'request changed'):
            remote.unpack(data, self.root / 'rejected', dict(self.request, nativeToolchain='b'*64))

    def test_archive_paths_links_duplicates_and_expansion_reject(self):
        for names, mode in ((['../escape'], 0o100644), (['payload/link'], 0o120777),
                            (['payload/a', 'payload/a'], 0o100644), (['payload/a'], 0o104644)):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                for name in names:
                    info = zipfile.ZipInfo(name); info.external_attr = mode << 16
                    archive.writestr(info, b'content')
            with self.assertRaisesRegex(IdentityError, 'archive member'): remote.unpack(buffer.getvalue(), self.root / 'bad', self.request)
        with patch.object(remote, 'MAX_ARCHIVE', 1), self.assertRaises(IdentityError):
            remote.unpack(b'xx', self.root / 'bad', self.request)

    def test_import_changed_between_download_and_install_rejects(self):
        generation = self.generation()
        expected = payload_identity(generation / 'payload')
        (generation / 'payload/program').write_bytes(b'changed')
        state = self.root / 'state'; state.mkdir()
        with self.assertRaisesRegex(IdentityError, 'changed during installation'):
            publish(state, self.root / 'old/workspace', generation / 'payload/graph.json', self.metadata['certificate'], self.request,
                imported_payload=generation / 'payload', imported_sha256=expected)
        self.assertFalse((state / 'current.json').exists())

    def test_native_fallback_uses_bound_prebuilt_tools(self):
        with patch('preparation_reuse.subprocess.run') as run, patch('native_graph.prepare_native'):
            with fresh_view(self.root / 'old/workspace', self.root / 'out', self.entries, native_toolchain='a'*64) as result:
                self.assertFalse(result['toolBuildsExecuted'])
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('build', run.call_args.args[0])
            self.assertIn('--request', run.call_args.args[0])

    def test_snapshot_hash_and_record_validation(self):
        value = dict(policy=remote_snapshot.POLICY, preparation=None, projects=[])
        data = json.dumps(value).encode()
        with patch.object(remote_snapshot, 'fetch', return_value=data):
            self.assertEqual(remote_snapshot.download('http://cache', remote.sha(data)), value)
            with self.assertRaisesRegex(ValueError, 'digest mismatch'): remote_snapshot.download('http://cache', 'a'*64)
        value['preparation'] = '../unsafe'
        with self.assertRaises(ValueError): remote_snapshot.validate(value)


if __name__ == '__main__': unittest.main()
