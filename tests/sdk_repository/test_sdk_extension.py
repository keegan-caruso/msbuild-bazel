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
    def check(self, declaration='global_json="//:global.json"', contents=None, error=None, metadata_version='10.0.400', options=()):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'global.json').write_text(contents or '{"sdk":{"version":"10.0.400"}}')
            (root/'BUILD.bazel').write_text('exports_files(["global.json"])')
            metadata = {'releases': [{'sdk': {'version': metadata_version, 'runtime-version': '10.0.11', 'files': [
                {'rid': rid, 'name': 'dotnet-sdk-' + rid + '.tar.gz', 'url': 'https://example.invalid/sdk.tar.gz', 'hash': '00' * 64}
                for rid in ['linux-arm64', 'linux-x64', 'osx-arm64', 'osx-x64']
            ]}}]}
            (root/'releases.json').write_text(json.dumps(metadata))
            declaration += ',metadata_urls=[' + json.dumps((root/'releases.json').as_uri()) + ']'
            (root/'MODULE.bazel').write_text('bazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",'+declaration+')\nuse_repo(dotnet,"dotnet")\n')
            result=subprocess.run([BAZEL,'--batch','--output_base='+str(root/'base'),'--ignore_all_rc_files','query','@dotnet//:all','--lockfile_mode=off',*options],cwd=root,text=True,capture_output=True,timeout=120)
            output=result.stdout+result.stderr
            if error:
                self.assertNotEqual(result.returncode,0,output)
                self.assertIn(error,output)
            else:
                self.assertEqual(result.returncode,0,output)
                self.assertIn('sdk_linux_arm64',output)
                self.assertIn('runtime_osx_arm64',output)
                self.assertIn('@dotnet//:sdk_host',output)

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
        self.check(contents='{"sdk":{"version":"10.0.400","rollForward":"latestMajor"}}',error='rollForward must be disable, patch, latestPatch or latestFeature')

    def test_latest_patch(self):
        self.check(contents='{"sdk":{"version":"10.0.399","rollForward":"latestPatch"}}',error='no SDK satisfying global.json')
        self.check(contents='{"sdk":{"version":"10.0.400","rollForward":"latestPatch"}}')

    def test_latest_feature(self):
        self.check(contents='{"sdk":{"version":"10.0.100","rollForward":"latestFeature"}}')

    def test_policy_case(self):
        self.check(contents='{"sdk":{"version":"10.0.100","rollForward":"LATESTFEATURE"}}')

    def test_update_unknown_sdk(self):
        self.check(options=['--repo_env=RULES_MSBUILD_SDK_UPDATE=missing:request'],error='root module: missing')

    def test_update_exact_sdk(self):
        self.check('version="10.0.400"',options=['--repo_env=RULES_MSBUILD_SDK_UPDATE=dotnet:request'],error='edit the exact version pin')

    def test_update_disabled(self):
        self.check(contents='{"sdk":{"version":"10.0.400","rollForward":"disable"}}',options=['--repo_env=RULES_MSBUILD_SDK_UPDATE=dotnet:request'],error='roll-forward is disabled')

    def test_explicit_prerelease(self):
        self.check(contents='{"sdk":{"version":"10.0.400-preview.1","rollForward":"latestPatch","allowPrerelease":false}}',metadata_version='10.0.400-preview.2')

    def test_machine_local_paths_rejected(self):
        self.check(contents='{"sdk":{"version":"10.0.400","paths":[".dotnet"]}}',error='Unsupported global.json sdk field: paths')

    def test_non_sdk_fields_rejected(self):
        self.check(contents='{"sdk":{"version":"10.0.400"},"test":{"runner":"Microsoft.Testing.Platform"}}',error='Unsupported global.json field: test')

    def test_msbuild_sdks(self):
        self.check(contents='{"sdk":{"version":"10.0.400"},"msbuild-sdks":{"Example.Sdk":"1.0.0"}}')
        self.check(contents='{"sdk":{"version":"10.0.400"},"msbuild-sdks":{"Example.Sdk":42}}',error="msbuild-sdks")

    def test_unknown_pin(self):
        self.check('version="99.0.100"',error='Release metadata must identify exactly one SDK')
