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
