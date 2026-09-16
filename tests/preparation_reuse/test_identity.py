"""Discovery identity mutation and failure controls without enabling reuse."""
import copy
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from preparation_identity import capture, compare, IdentityError, tree_snapshot


class DiscoveryIdentity(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.roots = {name: self.root / name for name in ('workspace', 'sdk', 'adapter', 'external')}
        for path in self.roots.values(): path.mkdir()
        self.workspace = self.roots['workspace']
        for name, value in {
            'App.csproj':'<Project><ProjectReference Include="Shared.csproj" /></Project>',
            'Program.cs':'class A {}', 'Directory.Build.props':'<Project />',
            'obj/project.assets.json':'{"libraries":{}}',
            'obj/project.nuget.cache':'{"success":true}',
            '.nuget/packages/example/1.0/example.nupkg':'archive',
            '.nuget/packages/example/1.0/lib/example.dll':'payload',
        }.items():
            path = self.workspace/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        (self.roots['sdk']/'compiler.dll').write_bytes(b'compiler')
        (self.roots['adapter']/'policy.json').write_text('{}')
        self.request = {'entryPoints':[{'project':'App.csproj','globalProperties':{'Configuration':'Release'}}], 'tests':[]}
        self.environment = {'PATH':'/fixed/tools', 'HOME':'/fixed/home', 'PRIVATE_VALUE':'do-not-report'}
        self.host = {'platform':'test', 'architecture':'arm64'}
        self.baseline = self.snapshot()

    def tearDown(self): self.temporary.cleanup()

    def snapshot(self):
        return capture(self.roots, request=self.request, environment=self.environment, host=self.host)

    def changed(self, domain):
        change = compare(self.baseline, self.snapshot())
        self.assertFalse(change['unchanged'])
        self.assertIn(domain, change['changedDomains'])

    def test_unchanged_bytes_and_membership_are_stable(self):
        self.assertEqual(self.baseline, self.snapshot())
        self.assertTrue(compare(self.baseline,self.snapshot())['unchanged'])

    def test_parallel_capture_matches_serial_capture(self):
        from concurrent.futures import ThreadPoolExecutor
        with patch('preparation_identity.ThreadPoolExecutor',
                   side_effect=lambda **kwargs: ThreadPoolExecutor(max_workers=1)):
            serial = self.snapshot()
        self.assertEqual(serial, self.snapshot())

    def test_same_size_edit_with_restored_mtime_invalidates(self):
        path = self.workspace/'Program.cs'; times=path.stat()
        path.write_text('class B {}')
        os.utime(path,ns=(times.st_atime_ns,times.st_mtime_ns))
        self.changed('root:workspace')

    def test_touch_preserves_content_identity_but_does_not_authorize_reuse(self):
        path=self.workspace/'Program.cs';times=path.stat()
        os.utime(path,ns=(times.st_atime_ns,times.st_mtime_ns+1000000000))
        self.assertEqual(self.baseline['key'],self.snapshot()['key'])

    def test_new_source_and_optional_import_are_detected(self):
        for name in ('Added.cs','Optional.targets'):
            with self.subTest(name=name):
                path=self.workspace/name;path.write_text('new')
                self.changed('root:workspace');path.unlink()

    def test_source_removal_is_detected(self):
        (self.workspace/'Program.cs').unlink();self.changed('root:workspace')

    def test_empty_directory_membership_is_detected(self):
        path=self.workspace/'Optional';path.mkdir();self.changed('root:workspace')
        other=self.snapshot();path.rmdir()
        self.assertFalse(compare(other,self.snapshot())['unchanged'])

    def test_restore_and_package_changes_are_detected(self):
        for name in ('obj/project.assets.json','obj/project.nuget.cache',
                     '.nuget/packages/example/1.0/example.nupkg','.nuget/packages/example/1.0/lib/example.dll'):
            with self.subTest(name=name):
                path=self.workspace/name;old=path.read_bytes();path.write_bytes(old+b'changed')
                self.changed('root:workspace');path.write_bytes(old)

    def test_reference_role_metadata_change_is_detected(self):
        path=self.workspace/'App.csproj'
        path.write_text(path.read_text().replace('/>', 'ReferenceOutputAssembly="false" />'))
        self.changed('root:workspace')

    def test_sdk_adapter_and_declared_external_changes_are_detected(self):
        for name in ('sdk','adapter','external'):
            with self.subTest(name=name):
                path=self.roots[name]/'new.input';path.write_text('changed')
                self.changed('root:'+name);path.unlink()

    def test_configuration_and_test_contract_invalidate(self):
        self.request['entryPoints'][0]['globalProperties']['Configuration']='Debug'
        self.changed('requestSha256')
        self.request['entryPoints'][0]['globalProperties']['Configuration']='Release'
        self.request['tests']=['changed'];self.changed('requestSha256')

    def test_effective_environment_and_host_invalidate_without_exposing_values(self):
        self.environment['PRIVATE_VALUE']='another-secret';self.changed('environmentSha256')
        self.assertNotIn('another-secret',repr(self.snapshot()))
        self.assertNotIn('do-not-report',repr(self.baseline))
        self.host['architecture']='x64';self.changed('hostSha256')

    def test_file_mode_change_invalidates(self):
        path=self.workspace/'Program.cs';path.chmod(path.stat().st_mode ^ 0o100)
        self.changed('root:workspace')

    def test_inside_symlink_target_content_is_hashed(self):
        (self.workspace/'link').symlink_to('Program.cs')
        before=self.snapshot();(self.workspace/'Program.cs').write_text('changed')
        self.assertFalse(compare(before,self.snapshot())['unchanged'])

    def test_declared_external_symlink_is_hashed(self):
        target=self.roots['external']/'file';target.write_text('v1')
        (self.workspace/'link').symlink_to(target)
        before=self.snapshot();target.write_text('v2')
        self.assertFalse(compare(before,self.snapshot())['unchanged'])

    def test_allowed_root_does_not_admit_a_sibling_prefix(self):
        sibling = self.root / 'sdk-extra'
        sibling.mkdir()
        target = sibling / 'compiler.dll'
        target.write_text('outside')
        (self.workspace / 'link').symlink_to(target)
        with self.assertRaisesRegex(IdentityError, 'undeclared symlink'):
            self.snapshot()

    def test_filesystem_root_allows_descendants(self):
        target = self.roots['external'] / 'unicode-é'
        target.write_text('allowed')
        (self.workspace / 'link').symlink_to(target)
        snapshot = tree_snapshot(self.workspace, [Path(self.workspace.anchor)])
        self.assertTrue(any(entry['path'] == './link/@target' for entry in snapshot['entries']))

    def test_undeclared_or_missing_symlink_target_is_rejected(self):
        target=self.root/'outside';target.write_text('v1')
        link=self.workspace/'link';link.symlink_to(target)
        with self.assertRaisesRegex(IdentityError,'undeclared symlink'): self.snapshot()
        target.unlink()
        with self.assertRaisesRegex(IdentityError,'missing or unreadable'): self.snapshot()

    def test_symlink_cycle_and_special_files_are_rejected(self):
        link=self.workspace/'cycle';link.symlink_to(self.workspace)
        with self.assertRaisesRegex(IdentityError,'symlink cycle'): self.snapshot()
        link.unlink();os.mkfifo(self.workspace/'pipe')
        with self.assertRaisesRegex(IdentityError,'unsupported filesystem'): self.snapshot()

    def test_missing_root_and_unknown_schema_are_rejected(self):
        shutil.rmtree(self.roots['external'])
        with self.assertRaisesRegex(IdentityError,'missing discovery root'): self.snapshot()
        with self.assertRaisesRegex(IdentityError,'unsupported discovery identity schema'):
            capture({},request={},environment={},host={},schema=999)

    def test_corrupt_identity_is_rejected(self):
        altered=copy.deepcopy(self.baseline);altered['key']='0'*64
        with self.assertRaisesRegex(IdentityError,'corrupt discovery identity'): compare(altered,self.baseline)

    def test_relocation_intentionally_changes_identity(self):
        target=self.root/'moved';shutil.copytree(self.workspace,target)
        self.roots['workspace']=target;self.changed('root:workspace')

    def test_there_are_no_implicit_build_or_gitignore_exclusions(self):
        for name in ('bin/extra.input','.git/config','.ignored'):
            with self.subTest(name=name):
                path=self.workspace/name;path.parent.mkdir(exist_ok=True)
                path.write_text('new');self.changed('root:workspace');path.unlink()

    def test_symlink_chain_cycle_fails_with_identity_error(self):
        (self.workspace/'a').symlink_to('b')
        (self.workspace/'b').symlink_to('a')
        with self.assertRaises(IdentityError): self.snapshot()

    def test_incomplete_or_corrupt_persisted_snapshots_fail_closed(self):
        for field in ('roots', 'requestSha256', 'snapshots'):
            broken=copy.deepcopy(self.baseline);del broken[field]
            with self.subTest(field=field), self.assertRaises(IdentityError): compare(broken,self.baseline)
        broken=copy.deepcopy(self.baseline)
        broken['snapshots']['workspace']['entries'][0]['mode']=0
        with self.assertRaises(IdentityError): compare(broken,self.baseline)
        broken=copy.deepcopy(self.baseline);broken['snapshots']['workspace']['bytesHashed']+=1
        with self.assertRaises(IdentityError): compare(broken,self.baseline)

    def test_mutation_of_already_read_file_is_rejected(self):
        original=Path.open
        mutated=False
        def changing_open(path,*args,**kwargs):
            nonlocal mutated
            if path.name=='policy.json' and not mutated:
                # Same tree: the file sorts before policy.json and has been read.
                mutated=True
                with original(path.parent/'first.txt','w') as stream: stream.write('changed')
            return original(path,*args,**kwargs)
        (self.roots['adapter']/'first.txt').write_text('before')
        with patch.object(Path,'open',changing_open), self.assertRaisesRegex(IdentityError,'changed during traversal'):
            self.snapshot()
