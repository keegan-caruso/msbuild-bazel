"""Qualified pilot packages retain archive integrity and ordinary declarations."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import graph_packages


class PilotPolicy(unittest.TestCase):
    def test_only_qualified_bare_versions(self):
        self.assertEqual(graph_packages.selected_version('PolySharp', '1.15.0'), '1.15.0')
        self.assertEqual(graph_packages.selected_version('PolySharp', '1.16.0'), '1.16.0')
        self.assertEqual(graph_packages.selected_version('Microsoft.NET.ILLink.Tasks', '10.0.0'), '10.0.0')
        self.assertEqual(graph_packages.selected_version('Example', '[1.0.0]'), '1.0.0')
        for package, version in [('Example', '1.0.0'), ('PolySharp', '1.15.1'), ('PolySharp', '1.*'), ('PolySharp', '[1.15.0,2.0.0)')]:
            with self.subTest(package=package, version=version), self.assertRaisesRegex(ValueError, 'unsupported-package'):
                graph_packages.selected_version(package, version)

    def test_repacked_qualified_identity_cannot_self_authorize(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            (work / 'App/obj').mkdir(parents=True)
            (work / 'App/App.csproj').write_text('<Project><ItemGroup><PackageReference Include="PolySharp" Version="1.15.0" /></ItemGroup></Project>')
            folder = work / '.nuget/packages/polysharp/1.15.0'
            folder.mkdir(parents=True)
            archive = folder / 'polysharp.1.15.0.nupkg'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('analyzers/evil.dll', b'not the qualified package')
            raw = archive.read_bytes()
            identity = 'PolySharp/1.15.0'
            (work / 'App/obj/project.assets.json').write_text(json.dumps(dict(
                libraries={identity:dict(type='package', path='polysharp/1.15.0', sha512=graph_packages.PILOT_PACKAGES['polysharp/1.15.0']['restoreContentHash'])},
                targets={'net10.0':{identity:dict(build={'build/PolySharp.targets':{}})}})))
            with self.assertRaisesRegex(ValueError, 'hash-mismatch: package archive differs from qualified pilot pin'):
                graph_packages.stage(work, 'App/App.csproj', work / 'output', 'node')
            self.assertFalse((work / 'output/package-manifests/node.json').exists())


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE') and os.environ.get('SPIKE_SERILOG_PACKAGES'), 'requires acquired pinned Serilog source/packages')
class PinnedSerilogPackagePolicy(unittest.TestCase):
    def test_unchanged_library_export_and_payload_integrity(self):
        source = Path(os.environ['SPIKE_SERILOG_SOURCE'])
        revision = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
        self.assertEqual(subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'], text=True).strip(), revision)
        evidence = Path(tempfile.mkdtemp(prefix='serilog-package-policy-')).resolve()
        work = evidence / 'source'
        with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['git','-C',str(source),'archive',revision]))) as archive:
            archive.extractall(work, filter='data')
        for identity in graph_packages.PILOT_PACKAGES:
            shutil.copytree(Path(os.environ['SPIKE_SERILOG_PACKAGES']) / identity, work / '.nuget/packages' / identity)
        sdk = Path(os.environ['SPIKE_DOTNET_ROOT'])
        env = dict(os.environ, NUGET_PACKAGES=str(work / '.nuget/packages'), DOTNET_CLI_HOME=str(evidence / 'home'), MSBUILDDISABLENODEREUSE='1')
        def run(name, args, error=None):
            result = subprocess.run([str(sdk/'dotnet'), *map(str,args)], cwd=work, env=env, capture_output=True, text=True, timeout=240)
            (evidence/(name+'.log')).write_text(result.stdout+result.stderr)
            if error:
                self.assertNotEqual(result.returncode,0)
                self.assertIn(error,result.stderr)
            else: self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        project = 'src/Serilog/Serilog.csproj'
        run('restore',['msbuild',project,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-nodeReuse:false','-nologo'])
        run('exporter-build',['build',ROOT/'tools/GraphExport','-c','Release','--nologo'])
        manifest = evidence/'graph.json'
        request = evidence/'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1,workspace=str(work),dotnetRoot=str(sdk),sdkVersion='10.0.100',packageRoot=str(work/'.nuget/packages'),entryPoints=[dict(project=project,globalProperties={'Configuration':'Release','TargetFramework':'net10.0'})],output=str(manifest))))
        run('export',[ROOT/'tools/GraphExport/bin/Release/net10.0/GraphExport.dll','--request',request])
        self.assertTrue(manifest.is_file())
        plan, files = graph_packages.stage(work, project, evidence/'staged', 'serilog')
        payload = json.loads((evidence/'staged'/plan).read_text())
        self.assertEqual(sorted(p['id']+'/'+p['version'] for p in payload['packages']), ['Microsoft.NET.ILLink.Tasks/10.0.0','PolySharp/1.15.0'])
        self.assertTrue(any('analyzers/dotnet/cs/PolySharp.SourceGenerators.dll' in f for f in files))
        self.assertTrue(any('build/PolySharp.targets' in f for f in files))
        assets_path = work/'src/Serilog/obj/project.assets.json'
        original_assets = assets_path.read_text()
        modified = json.loads(original_assets)
        modified['libraries']['PolySharp/1.15.0']['sha512'] = 'changed'
        assets_path.write_text(json.dumps(modified))
        with self.assertRaisesRegex(ValueError, 'hash-mismatch: package archive disagrees with restore'):
            graph_packages.stage(work, project, evidence/'wrong-restore-hash', 'serilog')
        assets_path.write_text(original_assets)
        generator = work/'.nuget/packages/polysharp/1.15.0/analyzers/dotnet/cs/PolySharp.SourceGenerators.dll'
        generator.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'hash-mismatch: package payload'):
            graph_packages.stage(work,project,evidence/'corrupt','serilog')
        self.assertFalse((evidence/'corrupt/package-manifests/serilog.json').exists())
        print('Pinned package policy evidence: '+str(evidence),flush=True)


if __name__ == '__main__': unittest.main()
