"""Package directory handoff must retain staging and payload integrity guards."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])


class PackageDirectories(unittest.TestCase):
    @unittest.skipUnless(sys.platform=='darwin','Owned workflow currently requires macOS')
    def test_borrowing_requires_project_and_package_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir()
            for projects,packages in [(False,False),(True,False),(False,True)]:
                request=root/'request.json';request.write_text(json.dumps(dict(
                    schemaVersion=1,repository=str(ROOT),workspace=str(source),state=str(root/'state'),
                    output=str(root/'output'),sdkRoot=str(SDK),bazel=os.environ['RULES_MSBUILD_BAZEL'],
                    entry='App.csproj',operation='build',
                    **{'borrow-package-inputs':True,'project-actions':projects,'package-actions':packages})))
                result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),
                    'owned-workflow','--request',str(request)],capture_output=True,text=True,timeout=30)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('Borrowed package inputs require project and package actions',result.stderr)

    def test_staging_sandbox_links_and_rejection_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tree=root/'tree';tree.mkdir();real=root/'actual';real.write_bytes(b'package');real.chmod(0o444);(tree/'payload').symlink_to(real)
            for case in ['valid','duplicate','escape','overlap']:
                with self.subTest(case=case):
                    workspace=root/case;row=dict(source=str(tree),package='package/1.0.0');rows=[row]
                    if case=='duplicate':rows=[row,row]
                    if case=='escape':rows=[dict(source=str(tree),package='../escape')]
                    target=workspace/'.nuget/packages/package/1.0.0/payload'
                    if case=='overlap':target.parent.mkdir(parents=True);target.write_bytes(b'original')
                    request=root/'request.json';request.write_text(json.dumps(dict(workspace=str(workspace),packageDirectories=rows)))
                    p=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),'stage-package-directories',str(request)],capture_output=True,text=True,timeout=30)
                    self.assertEqual(p.returncode==0,case=='valid',p.stderr)
                    if case=='valid':self.assertEqual(target.read_bytes(),b'package');self.assertFalse(target.is_symlink())
                    if case=='overlap':self.assertEqual(target.read_bytes(),b'original')
                    self.assertEqual(real.read_bytes(),b'package')

    def test_compiler_rejects_changed_tree_payload_and_bad_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tree=root/'tree';tree.mkdir();(tree/'file.dll').write_bytes(b'changed');plan=root/'plan';plan.mkdir()
            (plan/'payload.json').write_text(json.dumps({'.nuget/packages/package/1.0.0/file.dll':hashlib.sha256(b'expected').hexdigest()}))
            for case,packages,error in [('changed',[dict(source=str(tree),package='package/1.0.0')],'Prepared payload differs'),('escape',[dict(source=str(tree),package='../escape')],'Invalid or duplicate'),('duplicate',[dict(source=str(tree),package='package/1.0.0')]*2,'Invalid or duplicate')]:
                request=root/'request.json';request.write_text(json.dumps(dict(entry='App.csproj',output=str(root/case),diagnostics=str(root/(case+'-diagnostics')),manifest=str(plan/'manifest.json'),restore=str(plan/'restore.json'),sources=[],seeds=[],preparedPlan=str(plan),packageDirectories=packages)))
                p=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'),'--portable-request',str(request)],capture_output=True,text=True,timeout=30)
                self.assertNotEqual(p.returncode,0);self.assertIn(error,p.stderr);self.assertFalse((root/(case+'-diagnostics/action.json')).exists())
