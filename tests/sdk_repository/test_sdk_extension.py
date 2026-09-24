"""SDK pin resolution and global.json validation through Bzlmod."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
BAZEL=os.environ.get('RULES_MSBUILD_BAZEL',str(ROOT/'scripts/bazel-launcher.sh'))


class SdkExtension(unittest.TestCase):
    def check(self, declaration='global_json="//:global.json"', contents=None, error=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'global.json').write_text(contents or '{"sdk":{"version":"10.0.400"}}')
            (root/'BUILD.bazel').write_text('exports_files(["global.json"])')
            (root/'MODULE.bazel').write_text('bazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",'+declaration+')\nuse_repo(dotnet,"dotnet")\n')
            result=subprocess.run([BAZEL,'--batch','--output_base='+str(root/'base'),'--ignore_all_rc_files','query','@dotnet//:all','--lockfile_mode=off'],cwd=root,text=True,capture_output=True,timeout=120)
            output=result.stdout+result.stderr
            if error:
                self.assertNotEqual(result.returncode,0,output)
                self.assertIn(error,output)
            else:
                self.assertEqual(result.returncode,0,output)
                self.assertIn('sdk_linux_arm64',output)
                self.assertIn('runtime_osx_arm64',output)

    def test_exact_version(self):
        self.check('version="10.0.400"')

    def test_global_json_comments(self):
        self.check(contents='''{"$schema":"https://example.test/global.json", /* block */
            "sdk":{"version":"10.0.400", "rollForward":"disable", "allowPrerelease":false}} // tail''')

    def test_global_json_default_patch(self):
        self.check()

    def test_ambiguous_declaration(self):
        self.check('version="10.0.400",global_json="//:global.json"',error='Specify exactly one')

    def test_missing_version(self):
        self.check(contents='{"sdk":{}}',error='requires sdk.version')

    def test_unsupported_rollforward(self):
        self.check(contents='{"sdk":{"version":"10.0.400","rollForward":"latestPatch"}}',error='rollForward must be disable or patch')

    def test_machine_local_paths_rejected(self):
        self.check(contents='{"sdk":{"version":"10.0.400","paths":[".dotnet"]}}',error='Unsupported global.json sdk field: paths')

    def test_non_sdk_fields_rejected(self):
        self.check(contents='{"sdk":{"version":"10.0.400"},"test":{"runner":"Microsoft.Testing.Platform"}}',error='Unsupported global.json field: test')

    def test_unknown_pin(self):
        self.check('version="99.0.100"',error='Unknown pinned SDK version')
