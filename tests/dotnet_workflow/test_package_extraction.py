"""Extraction actions preserve NuGet paths and reject corrupt/escaping inputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class PackageExtraction(unittest.TestCase):
    def invoke(self, root, entries, *, digest=None, pin=None, label='output'):
        archive = root / 'test.nupkg'
        with zipfile.ZipFile(archive, 'w') as package:
            for name, data in entries: package.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)) if isinstance(name, str) else name, data)
        content_hash = base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
        request = root / 'request.json'
        request.write_text(json.dumps(dict(package='test/1.0.0', archive=str(archive),
            output=str(root / label), contentHash=digest or content_hash, pin=pin)))
        result = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'),
            str(ROOT / 'tools/Preparation/bin/Release/net10.0/Preparation.dll'),
            'owned-extract-package', '--request', str(request)], capture_output=True, text=True, timeout=20)
        return result, content_hash

    def test_paths_metadata_and_repeat_are_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            entries = [('Test.NUSPEC', '<package/>'), ('lib/net%2Bportable/a', 'one'), ('lib/other%2bportable/b', 'two')]
            first, digest = self.invoke(root, entries)
            self.assertEqual(first.returncode, 0, first.stderr)
            output = root / 'output'
            self.assertEqual((output / 'lib/net+portable/a').read_text(), 'one')
            self.assertEqual((output / 'lib/other+portable/b').read_text(), 'two')
            self.assertTrue((output / 'test.nuspec').exists())
            self.assertEqual(json.loads((output / '.nupkg.metadata').read_text())['contentHash'], digest)
            self.assertEqual((output / 'test.1.0.0.nupkg.sha512').read_text(), digest)
            second, _ = self.invoke(root, entries, label='repeat')
            self.assertEqual(second.returncode, 0, second.stderr)
            for path in output.rglob('*'):
                if path.is_file(): self.assertEqual(path.read_bytes(), (root / 'repeat' / path.relative_to(output)).read_bytes())

    def test_invalid_archive_inputs_fail(self):
        link = zipfile.ZipInfo('link'); link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [([('../escape', 'bad')], None), ([('/absolute', 'bad')], None),
            ([('lib/net%2Bportable/a', 'one'), ('lib/net+portable/a', 'two')], None),
            ([('lib/net%2Bportable/a', 'one'), ('lib/net+portable/b', 'two')], None),
            ([('.nupkg.metadata', 'bad')], None), ([(link, '../escape')], None),
            ([('lib/a', 'good')], base64.b64encode(bytes(64)).decode())]
        for entries, digest in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as folder:
                result, _ = self.invoke(Path(folder), entries, digest=digest)
                self.assertNotEqual(result.returncode, 0)


    def test_qualified_signed_hash_mapping_requires_both_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); entries = [('test.nuspec', '<package/>')]
            first, archive_hash = self.invoke(root, entries)
            self.assertEqual(first.returncode, 0, first.stderr)
            content = base64.b64encode(b'x' * 64).decode()
            pin = dict(restoreContentHash=content, archiveSha256=hashlib.sha256((root / 'test.nupkg').read_bytes()).hexdigest())
            result, _ = self.invoke(root, entries, digest=content, pin=pin, label='pinned')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((root / 'pinned/test.1.0.0.nupkg.sha512').read_text(), archive_hash)
            self.assertEqual(json.loads((root / 'pinned/.nupkg.metadata').read_text())['contentHash'], content)
            for field in ['restoreContentHash', 'archiveSha256']:
                invalid = dict(pin); invalid[field] = 'invalid'
                result, _ = self.invoke(root, entries, digest=content, pin=invalid, label='invalid-' + field)
                self.assertNotEqual(result.returncode, 0)
