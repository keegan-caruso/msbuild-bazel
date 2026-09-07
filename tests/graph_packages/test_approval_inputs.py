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
from prepare_graph_tests import add_tests


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE') and os.environ.get('SPIKE_SERILOG_PACKAGES'), 'requires acquired pinned Serilog source/packages')
class ApprovalInputs(unittest.TestCase):
    def test_unchanged_approval_complete_packages(self):
        source = Path(os.environ['SPIKE_SERILOG_SOURCE'])
        revision = '49b5339ce85385dc52d4d8e8f2b8308becf23506'
        self.assertEqual(subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'], text=True).strip(), revision)
        evidence = Path(tempfile.mkdtemp(prefix='serilog-approval-inputs-')).resolve()
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
        project = 'test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj'
        run('restore',['msbuild',project,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-nodeReuse:false','-nologo'])
        plan, files = graph_packages.stage(work, project, evidence/'staged', 'approval')
        payload = json.loads((evidence/'staged'/plan).read_text())
        self.assertEqual(len(payload['packages']), 20)
        self.assertTrue(any('/system.management/6.0.1/runtimes/win/' in f for f in files))
        self.assertTrue(any('/xunit.analyzers/1.16.0/analyzers/' in f for f in files))
        assets = json.loads((work/'test/Serilog.ApprovalTests/obj/project.assets.json').read_text())
        selected = next(iter(assets['targets'].values()))
        resource_count = sum(len(v.get('resource', {})) for v in selected.values())
        self.assertEqual(resource_count, 65)
        for identity, entry in selected.items():
            if assets['libraries'][identity]['type'] != 'package': continue
            for role in ('compile', 'runtime', 'resource', 'runtimeTargets'):
                for relative in entry.get(role, {}):
                    self.assertIn('packages/'+identity.lower()+'/'+relative, files)
        self.assertTrue(any(f.endswith('/Microsoft.NET.Test.Sdk.Program.cs') for f in files))
        self.assertTrue(any('/emptyfiles/4.4.0/EmptyFiles/' in f for f in files))
        run('exporter-build', ['build', ROOT/'tools/GraphExport', '-c', 'Release', '--nologo', '-nodeReuse:false'])
        manifest = evidence / 'graph.json'
        request = evidence / 'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(work), dotnetRoot=str(sdk),
            sdkVersion='10.0.100', packageRoot=str(work/'.nuget/packages'),
            entryPoints=[dict(project=project, globalProperties={'Configuration':'Release', 'TargetFramework':'net10.0'})], output=str(manifest))))
        run('export', [ROOT/'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request])
        graph = json.loads(manifest.read_text())
        self.assertEqual({node['project'] for node in graph['nodes']},
                         {'workspace/'+project, 'workspace/src/Serilog/Serilog.csproj'})
        self.assertTrue(all(node['targetFramework'] == 'net10.0' for node in graph['nodes']))
        self.assertFalse(list(work.glob('**/bin/**/*.dll')))
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/'+project)
        inputs = {(item['kind'], item['path']): item for item in entry['inputs']}
        program = 'workspace/.nuget/packages/microsoft.net.test.sdk/17.11.1/build/netcoreapp3.1/Microsoft.NET.Test.Sdk.Program.cs'
        self.assertEqual(inputs[('source', program)]['sha256'], hashlib.sha256((work/program.removeprefix('workspace/')).read_bytes()).hexdigest())
        empty_root = work/'.nuget/packages/emptyfiles/4.4.0/EmptyFiles'
        empty_files = sorted(path for path in empty_root.rglob('*') if path.is_file())
        self.assertEqual(len(empty_files), 42)
        for path in empty_files:
            item = inputs[('content', 'workspace/'+path.relative_to(work).as_posix())]
            self.assertEqual(item['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(item['metadata']['CopyToOutputDirectory'], 'PreserveNewest')
            self.assertEqual(item['metadata']['TargetPath'].replace('\\', '/'), 'EmptyFiles/'+path.relative_to(empty_root).as_posix())
        expected_packages = {
            'diffengine/11.3.0', 'emptyfiles/4.4.0', 'microsoft.codecoverage/17.11.1',
            'microsoft.net.test.sdk/17.11.1', 'microsoft.testplatform.objectmodel/17.11.1',
            'microsoft.testplatform.testhost/17.11.1', 'mono.cecil/0.11.5', 'newtonsoft.json/13.0.1',
            'publicapigenerator/11.1.0', 'shouldly/4.2.1', 'system.codedom/8.0.0', 'system.management/6.0.1',
            'xunit/2.9.2', 'xunit.abstractions/2.0.3', 'xunit.analyzers/1.16.0', 'xunit.assert/2.9.2',
            'xunit.core/2.9.2', 'xunit.extensibility.core/2.9.2', 'xunit.extensibility.execution/2.9.2',
            'xunit.runner.visualstudio/2.8.2'}
        self.assertEqual({identity.lower() for identity, value in assets['libraries'].items() if value['type']=='package'}, expected_packages)
        self.assertEqual({'/'.join(item['path'].removeprefix('workspace/.nuget/packages/').split('/')[:2])
                          for item in entry['inputs'] if item['kind']=='package'}, expected_packages)
        approved = 'test/Serilog.ApprovalTests/Serilog.approved.txt'
        self.assertFalse(any(item['path']=='workspace/'+approved for item in entry['inputs']))
        # Approval data is explicit test input, not an inferred build dependency.
        run('test-runner-build', ['build', ROOT/'tools/TestRunner', '-c', 'Release', '--nologo', '-nodeReuse:false'])
        test_plan = evidence/'test-plan'; test_plan.mkdir()
        add_tests(work, test_plan, {node['id']:node for node in graph['nodes']},
                  [dict(node=entry['id'], data=[approved], expectedTests=['ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally'])], ROOT)
        test_metadata = json.loads((test_plan/'tests.json').read_text())
        self.assertEqual(test_metadata['tests'][0]['dataHashes'][approved], hashlib.sha256((work/approved).read_bytes()).hexdigest())
        self.assertEqual((test_plan/'test-data'/approved).read_bytes(), (work/approved).read_bytes())
        assets_path = work/'test/Serilog.ApprovalTests/obj/project.assets.json'
        original_assets = assets_path.read_text()
        changed = json.loads(original_assets)
        next(iter(changed['targets'].values()))['DiffEngine/11.3.0']['native'] = {'native/unqualified.dll': {}}
        assets_path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'unsupported-package'):
            graph_packages.stage(work, project, evidence/'wrong-role', 'approval')
        assets_path.write_text(original_assets)
        archive = work/'.nuget/packages/microsoft.net.test.sdk/17.11.1/microsoft.net.test.sdk.17.11.1.nupkg'
        raw = archive.read_bytes()
        archive.write_bytes(raw+b'changed')
        with self.assertRaisesRegex(ValueError, 'hash-mismatch: package archive differs'):
            graph_packages.stage(work, project, evidence/'wrong-archive', 'approval')
        archive.write_bytes(raw)
        source_file = work/'.nuget/packages/microsoft.net.test.sdk/17.11.1/build/netcoreapp3.1/Microsoft.NET.Test.Sdk.Program.cs'
        source_file.write_bytes(b'altered source')
        with self.assertRaisesRegex(ValueError, 'hash-mismatch: package payload'):
            graph_packages.stage(work, project, evidence/'wrong-source', 'approval')
        print('Approval input evidence: '+str(evidence), flush=True)
