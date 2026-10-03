"""Shared artifact operations retain integrity checks without a compiler backend."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
RUNNER = ROOT/'tools/ArtifactTools/bin/Release/net10.0/ArtifactTools.dll'


class ArtifactToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='artifact-tools-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, operation, request, *args, success=True):
        path = self.root/'request.json'
        path.write_text(json.dumps(request))
        result = subprocess.run([str(SDK/'dotnet'), str(RUNNER), operation, str(path), *map(str,args)], capture_output=True, text=True, env=dict(os.environ,DOTNET_ROOT=str(SDK)))
        self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        return result.stdout+result.stderr

    def package(self, extra=None):
        path = self.root/'example.nupkg'
        with zipfile.ZipFile(path,'w') as archive:
            archive.writestr('Example.nuspec','<package><metadata><id>Example</id><version>1.0.0</version></metadata></package>')
            archive.writestr('lib/net10.0/Example.dll',b'fixture payload')
            if extra:
                archive.writestr(extra,'escaped')
        data=path.read_bytes()
        return dict(id='Example',version='1.0.0',archive=str(path),archiveSha256=hashlib.sha256(data).hexdigest(),contentHash=base64.b64encode(hashlib.sha512(data).digest()).decode(),output=str(self.root/'package'))

    def test_locked_package_extracts(self):
        self.invoke('extract',self.package())
        self.assertEqual((self.root/'package/lib/net10.0/Example.dll').read_bytes(),b'fixture payload')

    def test_hash_and_identity_fail_closed(self):
        request=self.package()
        for field,value,message in [('archiveSha256','0'*64,'locked archive hash'),('contentHash',base64.b64encode(b'x').decode(),'content hash'),('id','Other','identity differs')]:
            with self.subTest(field=field):
                self.assertIn(message,self.invoke('extract',dict(request,**{field:value}),success=False))

    def test_zip_traversal_is_rejected(self):
        self.assertIn('Unsafe logical path',self.invoke('extract',self.package('../outside'),success=False))
        self.assertFalse((self.root/'outside').exists())

    def test_generated_package_has_no_acquired_hash(self):
        request=self.package()
        self.invoke('extract',dict(request,generated=True),success=False)
        self.invoke('extract',dict(request,generated=True,archiveSha256='',contentHash=''))

    def test_layout_conflicts_are_rejected(self):
        a,b=self.root/'a',self.root/'b'
        a.write_text('first');b.write_text('second')
        manifest=self.root/'manifest'
        manifest.write_text('\n'.join(json.dumps(dict(source=str(p),path='file')) for p in [a,b])+'\n')
        self.assertIn('Conflicting',self.invoke('layout',dict(output=str(self.root/'layout')),'@'+str(manifest),success=False))

    def test_native_archive_integrity(self):
        path=self.root/'native.tar.gz'
        with tarfile.open(path,'w:gz') as archive:
            for name in ['usr/bin/tool','etc/config']:
                entry=tarfile.TarInfo(name);entry.size=4
                archive.addfile(entry,io.BytesIO(b'tool'))
        request=dict(archive=str(path),archiveSha256=hashlib.sha256(path.read_bytes()).hexdigest(),output=str(self.root/'native'))
        self.invoke('native-toolchain',dict(request,archiveSha256='0'*64),success=False)
        self.invoke('native-toolchain',request)
        self.assertEqual((self.root/'native/usr/bin/tool').read_bytes(),b'tool')

    @unittest.skipUnless(os.name == 'posix' and shutil.which('dpkg-deb'), 'Linux package assembler')
    def test_native_package_linker_script_uses_declared_sysroot(self):
        package = self.root/'deb'
        (package/'DEBIAN').mkdir(parents=True)
        (package/'DEBIAN/control').write_text('Package: fixture\nVersion: 1.0\nArchitecture: all\nMaintainer: fixture\nDescription: native layout control\n')
        payloads = {
            'usr/lib/fixture/libc.so': b'/* GNU ld script\nGROUP ( /lib/fixture/libc.so.6 /usr/lib/fixture/libc_nonshared.a )\n',
            'lib/fixture/libc.so.6': b'locked native payload',
            'usr/lib/fixture/libc_nonshared.a': b'locked static payload',
            'usr/share/doc/fixture/copyright': b'fixture license',
            'etc/config': b'fixture config',
        }
        for name, data in payloads.items():
            path = package/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        archive = self.root/'fixture.deb'
        subprocess.run(['dpkg-deb', '--build', str(package), str(archive)], check=True, capture_output=True)
        manifest = self.root/'files.manifest'
        manifest.write_text('\n'.join(sorted(name.replace('lib/fixture/libc.so.6', 'usr/lib/fixture/libc.so.6') if name.startswith('lib/') else name for name in payloads))+'\n')
        output = self.root/'native'
        request = dict(packages=[dict(name='fixture', archive=str(archive), sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), licensePath='usr/share/doc/fixture/copyright')], manifest=str(manifest), output=str(output))
        self.invoke('native-toolchain-packages', request)
        self.assertIn(' /usr/lib/fixture/libc.so.6', (output/'usr/lib/fixture/libc.so').read_text())
        self.assertEqual((output/'usr/lib/fixture/libc.so.6').read_bytes(), payloads['lib/fixture/libc.so.6'])
        # Archive verification precedes any relocation of owned files.
        archive.write_bytes(b'changed package')
        self.assertIn('locked SHA-256', self.invoke('native-toolchain-packages', dict(request, output=str(self.root/'bad')), success=False))

    def test_graph_output_requires_declared_ownership(self):
        workspace=self.root/'workspace';workspace.mkdir()
        (workspace/'source.txt').write_text('source')
        (workspace/'out').mkdir();(workspace/'out/product.nupkg').write_text('product')
        contract=self.root/'contract.json'
        contract.write_text(json.dumps({'Projects':{'App.csproj':{'Configurations':[{'OutputDirectories':['out']}]}}}))
        request=dict(contract=str(contract),workspace=str(workspace),path='out/product.nupkg',output=str(self.root/'export/product.nupkg'))
        self.invoke('graph-output',request)
        self.assertEqual((self.root/'export/product.nupkg').read_text(),'product')
        self.assertIn('not declared',self.invoke('graph-output',dict(request,path='source.txt'),success=False))
        self.assertIn('Missing graph output',self.invoke('graph-output',dict(request,path='out/missing'),success=False))

    def test_old_compilation_dispatch_is_removed(self):
        self.assertIn('Expected layout',self.invoke('build',{},success=False))


if __name__ == '__main__':
    unittest.main()
