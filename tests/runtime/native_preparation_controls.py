"""Small source-version and component archive controls; no SDK/native build needed."""
from collections import Counter
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from native_version import version_inputs


class NativePreparationTests(unittest.TestCase):
    def test_versions_come_from_source_and_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'eng/native/version').mkdir(parents=True)
            props = source / 'eng/Versions.props'
            props.write_text('<Project><PropertyGroup><ProductVersion>10.0.0</ProductVersion><MajorVersion>10</MajorVersion><MinorVersion>0</MinorVersion><PatchVersion>0</PatchVersion></PropertyGroup></Project>')
            (source / 'eng/native/version/_version.h').write_text('// authored header\n#define VER_PRODUCTVERSION 00,00,00,00000\n#define VER_PRODUCTVERSION_STR "0.0.0"\n')
            fields = ['RuntimeAssemblyMajorVersion', 'RuntimeAssemblyMinorVersion', 'RuntimeFileMajorVersion',
                'RuntimeFileMinorVersion', 'RuntimeFileBuildVersion', 'RuntimeFileRevisionVersion',
                'RuntimeProductMajorVersion', 'RuntimeProductMinorVersion', 'RuntimeProductPatchVersion', 'RuntimeProductVersion']
            (source / 'eng/native/version/runtime_version.h').write_text(''.join('#define ' + name + ' 0\n' for name in fields))
            (source / 'eng/native/version/_version.c').write_text('const char *version="@(#)No version information produced";')
            first = version_inputs(source, 'a' * 40)
            self.assertEqual(first, version_inputs(source, 'a' * 40))
            self.assertIn('#define RuntimeAssemblyMajorVersion 10\n', first['runtime_version.h'])
            self.assertTrue(first['_version.h'].startswith('// authored header\n'))
            self.assertIn('VER_PRODUCTVERSION 10,0,0,0', first['_version.h'])
            self.assertIn('10.0.0 @Commit: ' + 'a' * 40, first['_version.c'])
            with self.assertRaises(AssertionError):
                version_inputs(source, 'invalid')
            props.write_text(props.read_text().replace('<MajorVersion>10', '<MajorVersion>9'))
            with self.assertRaises(AssertionError):
                version_inputs(source, 'a' * 40)

    def test_components_keep_generated_headers_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'native'
            source.mkdir()
            files = {'artifacts/obj/_version.h': b'generated product 10.0.0',
                'artifacts/obj/runtime_version.h': b'generated runtime 10.0.0',
                'build-native.sh': b'old', 'src/native/keep.txt': b'authored'}
            with tarfile.open(source / 'source.tar', 'w') as archive:
                for name, body in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(body)
                    archive.addfile(member, io.BytesIO(body))
            for name in ['toolchain.tar', 'bwrap']:
                (source / name).write_bytes(b'declared')
            (source / 'Task.csproj').write_text('<Project/>')
            for component in ['host', 'support', 'crypto', 'compression']:
                output = Path(temporary) / component
                subprocess.run([sys.executable, str(Path(__file__).with_name('native_component_prepare.py')),
                    str(source), str(output), component, '--ninja'], check=True)
                with tarfile.open(output / 'source.tar') as archive:
                    self.assertTrue(all(count == 1 for count in Counter(member.name for member in archive).values()))
                    for name in ['artifacts/obj/_version.h', 'artifacts/obj/runtime_version.h', 'src/native/keep.txt']:
                        self.assertEqual(archive.extractfile(name).read(), files[name])
                    self.assertIn(b'-ninja', archive.extractfile('build-native.sh').read())


if __name__ == '__main__':
    unittest.main()
