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
            lock('B',{'net10.0':{'First':package('Transitive')},'net9.0':{'Second':package()}},2)
            self.assertEqual(invoke(['A/A.csproj','B/B.csproj'])['locked'],{'first/1.2.3':digest,'second/1.2.3':digest})
            lock('B',{'net10.0':{'First':package(hash_value=base64.b64encode(b'x'*64).decode())}})
            self.assertIn('Conflicting',invoke(['A/A.csproj','B/B.csproj'],False))
            for data in [package(hash_value='bad'),package(kind='Unknown'),dict(type='Transitive',resolved='../escape',contentHash=digest)]:
                lock('A',{'net10.0':{'First':data}});invoke(['A/A.csproj'],False)
            lock('A',{},99);self.assertIn('lock version',invoke(['A/A.csproj'],False))
            invoke(['Missing/Missing.csproj'],False)
