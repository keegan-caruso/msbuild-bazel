"""Actual Bazel repository evaluation, including fail-closed empty SDK behavior."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BAZEL = Path(os.environ.get('RULES_MSBUILD_BAZEL', ROOT / 'scripts/bazel-launcher.sh'))


class SdkRepository(unittest.TestCase):
    def check_repository(self, sdk, imports, succeeds):
        evidence = Path(tempfile.mkdtemp(prefix='sdk-repository-')).resolve()
        work = evidence / 'workspace'
        work.mkdir()
        shutil.copyfile(ROOT / 'bazel/msbuild.bzl', work / 'msbuild.bzl')
        (work / 'MODULE.bazel').write_text('local_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n' +
            'local_dotnet_sdk(name="dotnet", path=' + json.dumps(str(sdk)) + ', external_imports=' + json.dumps(imports) + ')\n')
        (work / 'BUILD.bazel').write_text('exports_files(["msbuild.bzl"])\n')
        result = subprocess.run([str(BAZEL), '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(evidence / 'base'), '--output_user_root=' + str(evidence / 'bazel-user'), 'cquery', '@dotnet//:files', '--output=files',
            '--noshow_progress', '--color=no', '--curses=no'], cwd=work, text=True, capture_output=True, timeout=120)
        (work / 'query.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_empty_optional_imports_and_nonempty_sdk(self):
        sdk = Path(tempfile.mkdtemp(prefix='sdk-stub-')).resolve()
        (sdk / 'dotnet').write_text('not executed by repository query\n')
        result = self.check_repository(sdk, [], True)
        self.assertIn('/sdk/dotnet', result)
        self.assertNotIn('/imports/', result)

    def test_empty_sdk_remains_rejected(self):
        sdk = Path(tempfile.mkdtemp(prefix='sdk-empty-')).resolve()
        result = self.check_repository(sdk, [], False)
        self.assertIn('glob', result)
        self.assertIn('sdk/**', result)

    def test_declared_nix_import_is_a_real_repository_input(self):
        sdk = os.environ.get('RULES_MSBUILD_DOTNET_ROOT', '')
        if not sdk.startswith('/nix/store/'):
            self.skipTest('requires acquired Nix SDK')
        imported = '/nix/store/7j5z3nhm7kqc12lw46153fbahbbdxf7k-extra.targets'
        if not Path(imported).is_file():
            self.skipTest('requires pinned macOS SDK import')
        result = self.check_repository(sdk, [imported], True)
        self.assertIn('/imports/0', result)
