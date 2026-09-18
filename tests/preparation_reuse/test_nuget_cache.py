import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import nuget_cache
import remote_packages
from preparation_identity import IdentityError
from portable_cache import sha
from probe_http_cache import CacheServer


class NuGetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.cache = self.root / 'global'; self.folder = self.cache / 'foo/1.0.0'
        (self.folder / 'lib').mkdir(parents=True)
        (self.folder / 'lib/Foo.dll').write_bytes(b'library')
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as z:
            z.writestr('lib/Foo.dll', b'library'); z.writestr('_rels/.rels', b'bookkeeping')
        self.archive = raw.getvalue()
        (self.folder / 'foo.1.0.0.nupkg').write_bytes(self.archive)
        self.source = self.root / 's'; (self.source / 'App/obj').mkdir(parents=True)
        self.assets = self.source / 'App/obj/project.assets.json'
        self.assets.write_text(json.dumps(dict(packageFolders={str(self.cache) + '/': {}}, libraries={'Foo/1.0.0': {'type': 'package', 'path': 'foo/1.0.0'}}, project={'restore': {'packagesPath': str(self.cache), 'projectPath': str(self.source / 'App/App.csproj')}})))
        self.destination = self.root / 'state/input'
        contents = {'lib/Foo.dll': b'library', '_rels/.rels': b'bookkeeping', 'foo.1.0.0.nupkg': self.archive,
            'foo.1.0.0.nupkg.sha512': base64.b64encode(hashlib.sha512(self.archive).digest())}
        self.blob = remote_packages.archive(contents)
        self.record = dict(path='foo/1.0.0', archiveSha256=sha(self.archive), blob=sha(self.blob),
            files=[dict(path=p, size=len(data), sha256=sha(data), mode=0o644) for p, data in contents.items()])

    def test_uses_nuget_environment_default(self):
        with patch.dict('os.environ', {'NUGET_PACKAGES': str(self.cache)}): self.assertEqual(nuget_cache.default_cache(), self.cache)

    def test_default_home_cache_when_environment_is_unset(self):
        with patch.dict('os.environ', {}, clear=True), patch('nuget_cache.Path.home', return_value=self.root / 'home'):
            self.assertEqual(nuget_cache.default_cache(), self.root / 'home/.nuget/packages')

    def test_get_put_only_service_is_supported(self):
        from urllib.error import HTTPError
        with patch('remote_packages.urlopen', side_effect=HTTPError('http://cache', 405, 'unsupported', {}, None)), patch('remote_packages.put') as put:
            key = remote_packages.upload('http://cache', self.blob)
            put.assert_called_once_with('http://cache/cas/' + key, self.blob)

    def test_only_selected_packages_are_copied_and_restore_paths_rebased(self):
        (self.cache / 'unrelated').mkdir(); (self.cache / 'unrelated/file').write_bytes(b'ignored')
        path, report = nuget_cache.stage(self.source, self.destination, self.cache)
        self.assertEqual(report['packages'], 1)
        assets = json.loads((path / 'App/obj/project.assets.json').read_text())
        self.assertEqual(assets['project']['restore']['packagesPath'], str(path / '.nuget/packages'))
        self.assertFalse((path / '.nuget/packages/unrelated').exists())
        (self.folder / 'lib/Foo.dll').write_bytes(b'changed after staging')
        self.assertEqual((path / '.nuget/packages/foo/1.0.0/lib/Foo.dll').read_bytes(), b'library')
        self.assertFalse((self.source / '.nuget/packages').exists())

    def test_linked_staging_destination_cannot_delete_other_directories(self):
        sentinel = self.root / 'keep'; sentinel.mkdir(); (sentinel / 'file').write_text('keep')
        self.destination.parent.mkdir(); self.destination.symlink_to(sentinel)
        with self.assertRaisesRegex(IdentityError, 'staging destination'):
            nuget_cache.stage(self.source, self.destination, self.cache)
        self.assertEqual((sentinel / 'file').read_text(), 'keep')

    def test_modified_prepared_package_is_never_uploaded(self):
        payload = self.root / 'payload'
        shutil.copytree(self.folder, payload / 'src/.nuget/packages/foo/1.0.0')
        (payload / 'package-manifests').mkdir()
        package = dict(self.record, files=[f for f in self.record['files'] if (self.folder / f['path']).exists()])
        (payload / 'package-manifests/node.json').write_text(json.dumps({'packages': [package]}))
        (payload / 'src/.nuget/packages/foo/1.0.0/lib/Foo.dll').write_bytes(b'modified')
        with patch('remote_packages.upload') as upload, self.assertRaisesRegex(IdentityError, 'verified manifest'):
            remote_packages.describe(payload, 'http://cache')
        upload.assert_not_called()

    def test_missing_package_requires_restore(self):
        shutil.rmtree(self.folder)
        with self.assertRaisesRegex(IdentityError, 'run restore'): nuget_cache.stage(self.source, self.destination, self.cache)

    def test_wrong_cache_and_escaping_package_reject(self):
        with self.assertRaisesRegex(IdentityError, 'different NuGet cache'): nuget_cache.stage(self.source, self.destination, self.root / 'other')
        assets = json.loads(self.assets.read_text()); assets['libraries']['Foo/1.0.0']['path'] = '../escape'
        self.assets.write_text(json.dumps(assets))
        with self.assertRaisesRegex(IdentityError, 'package path'): nuget_cache.stage(self.source, self.destination, self.cache)

    def test_package_mutation_during_copy_rejects(self):
        actual = shutil.copytree
        def changed(src, dst, *args, **kwargs):
            result = actual(src, dst, *args, **kwargs)
            if Path(src) == self.folder: (self.folder / 'lib/Foo.dll').write_bytes(b'mutated')
            return result
        with patch('nuget_cache.shutil.copytree', side_effect=changed), self.assertRaisesRegex(IdentityError, 'changed while staging'):
            nuget_cache.stage(self.source, self.destination, self.cache)

    def test_symlink_package_rejects(self):
        moved = self.root / 'moved'; self.folder.rename(moved); self.folder.symlink_to(moved)
        with self.assertRaisesRegex(IdentityError, 'linked NuGet package'): nuget_cache.stage(self.source, self.destination, self.cache)

    def test_cached_files_and_archive_bookkeeping_reconstruct_without_network(self):
        with patch('remote_packages.fetch', side_effect=AssertionError('unexpected download')):
            report = remote_packages.restore('http://unused', [self.record], self.destination, [self.cache])
        self.assertEqual(report['localPackages'], 1); self.assertEqual(report['remotePackages'], 0)
        self.assertEqual((self.destination / 'src/.nuget/packages/foo/1.0.0/_rels/.rels').read_bytes(), b'bookkeeping')

    def test_mutated_or_missing_cache_falls_back_to_verified_remote_bytes(self):
        (self.folder / 'lib/Foo.dll').write_bytes(b'corrupt')
        with patch('remote_packages.fetch', return_value=self.blob) as fetch:
            result = remote_packages.restore('http://unused', [self.record], self.destination, [self.cache])
        self.assertEqual(fetch.call_count, 1); self.assertEqual(result['remotePackages'], 1)
        self.assertEqual((self.folder / 'lib/Foo.dll').read_bytes(), b'corrupt')  # Never repair shared mutable state.
        self.assertEqual((self.destination / 'src/.nuget/packages/foo/1.0.0/lib/Foo.dll').read_bytes(), b'library')

    def test_corrupt_remote_or_local_archive_rejects(self):
        (self.folder / 'foo.1.0.0.nupkg').write_bytes(b'corrupt')
        with self.assertRaisesRegex(IdentityError, 'archive differs'): remote_packages.local_files(self.cache, self.record)
        with patch('remote_packages.fetch', return_value=b'corrupt'), self.assertRaisesRegex(IdentityError, 'digest mismatch'):
            remote_packages.restore('http://unused', [self.record], self.destination, [])

    def test_record_overlap_escape_and_expanded_limit_reject(self):
        name = 'payload/src/.nuget/packages/foo/1.0.0/lib/Foo.dll'
        with self.assertRaises(IdentityError): remote_packages.validate([self.record], {name}, 100000)
        with self.assertRaises(IdentityError): remote_packages.validate([self.record], set(), 1)
        with self.assertRaises(IdentityError): remote_packages.validate([dict(self.record, path='../bad')], set(), 100000)

    def test_unchanged_package_put_is_skipped_but_eviction_is_repaired(self):
        with CacheServer() as server:
            endpoint = server.url + '/native'
            first = remote_packages.upload(endpoint, self.blob)
            second = remote_packages.upload(endpoint, self.blob)
            self.assertEqual(first, second)
            self.assertEqual(sum(e['method'] == 'PUT' for e in server.events), 1)
            del server.data['/native/cas/' + first]
            remote_packages.upload(endpoint, self.blob)
            self.assertEqual(sum(e['method'] == 'PUT' for e in server.events), 2)


if __name__ == '__main__': unittest.main()
