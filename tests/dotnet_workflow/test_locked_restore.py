"""NuGet lock inputs must pin the complete closure and reject inconsistent hashes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class LockedRestore(unittest.TestCase):
    def test_complete_lock_closure_and_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);digest=base64.b64encode(bytes(range(64))).decode()
            def package(kind='Direct',hash_value=digest):return dict(type=kind,resolved='1.2.3',contentHash=hash_value)
            def lock(name,dependencies,version=1):
                path=root/name/'packages.lock.json';path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(dict(version=version,dependencies=dependencies)))
            def invoke(projects,success=True):
                request=root/'request.json';request.write_text(json.dumps(dict(workspace=str(root),projects=projects)))
                result=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),'describe-locks',str(request)],capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode==0,success,result.stderr)
                return json.loads(result.stdout) if success else result.stderr
            lock('A',{'net10.0':{'First':package(),'Dependency':dict(type='Project')}})
            lock('B',{'net10.0':{'First':package('Transitive')},'net9.0':{'Second':package('CentralTransitive')}},2)
            self.assertEqual(invoke(['A/A.csproj','B/B.csproj'])['locked'],{'first/1.2.3':digest,'second/1.2.3':digest})
            lock('B',{'net10.0':{'First':package(hash_value=base64.b64encode(b'x'*64).decode())}})
            self.assertIn('Conflicting',invoke(['A/A.csproj','B/B.csproj'],False))
            for data in [package(hash_value='bad'),package(kind='Unknown'),dict(type='Transitive',resolved='../escape',contentHash=digest)]:
                lock('A',{'net10.0':{'First':data}});invoke(['A/A.csproj'],False)
            lock('A',{},99);self.assertIn('lock version',invoke(['A/A.csproj'],False))
            invoke(['Missing/Missing.csproj'],False)

    @unittest.skipUnless(os.uname().sysname == 'Darwin', 'macOS sandbox qualification')
    def test_large_source_set_denies_bodies_but_allows_restore_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();workspace=root/'obj/parent/workspace';workspace.mkdir(parents=True)
            bodies=[f'Project{i}/Body.cs' for i in range(6000)]
            request=root/'request.json';request.write_text(json.dumps(dict(workspace=str(workspace),bodies=bodies)))
            command=[str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),'locked-source-profile',str(request)]
            policy=subprocess.run(command,capture_output=True,text=True,check=True).stdout
            profile=root/'sandbox.sb';profile.write_text('(version 1)\n(allow default)\n'+policy)
            for name,allowed in [('Project0/Body.cs',False),('obj/Body.cs',False),('Project5999/Body.cs',False),('Project0/App.csproj',True),('Project0/obj/Generated.cs',True),('.nuget/packages/p/Source.cs',True)]:
                path=workspace/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('sentinel')
                result=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),'/bin/cat',str(path)],capture_output=True,text=True)
                self.assertEqual(result.returncode==0,allowed,(name,result.stderr))
            for name in ['escape.txt','.nuget/Source.cs','App/obj/Source.cs']:
                request.write_text(json.dumps(dict(workspace=str(workspace),bodies=[name])))
                self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
