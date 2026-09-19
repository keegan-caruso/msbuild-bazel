"""Exercise NuGet path normalization through the actual Bazel repository rule."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get('RULES_MSBUILD_BAZEL'), 'pinned Bazel required')
class NuGetRepository(unittest.TestCase):
    def test_encoded_framework_paths_and_collision_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            for collision in [False,True]:
                workspace=root/str(collision);workspace.mkdir()
                cache=workspace/'cache/test/1.0.0';cache.mkdir(parents=True)
                archive=cache/'test.1.0.0.nupkg'
                with zipfile.ZipFile(archive,'w') as package:
                    package.writestr('Test.nuspec','<package><metadata><id>test</id><version>1.0.0</version></metadata></package>')
                    package.writestr('lib/net%2Bportable/test.txt','first')
                    if collision:package.writestr('lib/net+portable/test.txt','second')
                    else:package.writestr('lib/other%2bportable/test.txt','second')
                digest=base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()
                shutil.copy(ROOT/'bazel/repositories.bzl',workspace/'repositories.bzl')
                (workspace/'policy.json').write_text('{}')
                (workspace/'BUILD.bazel').write_text('exports_files(["policy.json"])\n')
                (workspace/'MODULE.bazel').write_text('module(name="nuget_path_probe")\nnuget_archives=use_repo_rule("//:repositories.bzl","nuget_archives")\nnuget_archives(name="nuget",cache='+json.dumps(str(workspace/'cache'))+',packages='+json.dumps(json.dumps({'test/1.0.0':digest}))+',policy="//:policy.json")\n')
                result=subprocess.run([os.environ['RULES_MSBUILD_BAZEL'],'--batch','--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_user_root='+str(root/'user'),'--output_base='+str(root/('base-'+str(collision))),'query','--incompatible_autoload_externally=','labels(srcs, @nuget//:files)'],cwd=workspace,capture_output=True,text=True,timeout=90)
                if collision:
                    self.assertNotEqual(result.returncode,0)
                    self.assertIn('Conflicting normalized NuGet path',result.stderr)
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertIn('lib/net+portable/test.txt',result.stdout)
                    self.assertIn('lib/other+portable/test.txt',result.stdout)
                    self.assertNotIn('%2',result.stdout)
                    self.assertIn('/test.nuspec',result.stdout)

    def test_empty_package_set_is_a_valid_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();workspace=root/'workspace';workspace.mkdir()
            shutil.copy(ROOT/'bazel/repositories.bzl',workspace/'repositories.bzl')
            (workspace/'policy.json').write_text('{}')
            (workspace/'BUILD.bazel').write_text('exports_files(["policy.json"])\n')
            (workspace/'MODULE.bazel').write_text('module(name="empty_nuget_probe")\nnuget_archives=use_repo_rule("//:repositories.bzl","nuget_archives")\nnuget_archives(name="nuget",cache='+json.dumps(str(root/'cache'))+',packages="{}",policy="//:policy.json")\n')
            result=subprocess.run([os.environ['RULES_MSBUILD_BAZEL'],'--batch','--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_user_root='+str(root/'user'),'--output_base='+str(root/'base'),'query','--incompatible_autoload_externally=','labels(srcs, @nuget//:files)'],cwd=workspace,capture_output=True,text=True,timeout=90)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),'')
