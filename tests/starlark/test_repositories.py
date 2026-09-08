"""S05: fresh/reused output bases, declared payloads, and exact repository failures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BAZEL = Path(os.environ.get('RULES_MSBUILD_BAZEL', ROOT / '.tools/bin/bazel'))


class RepositoryContracts(unittest.TestCase):
    def setUp(self):
        self.evidence = Path(tempfile.mkdtemp(prefix='starlark-repository-')).resolve()
        self.work = self.evidence / 'workspace'
        self.work.mkdir()
        print('Repository evidence: ' + str(self.evidence), file=sys.stderr)
        shutil.copyfile(ROOT / 'bazel/msbuild.bzl', self.work / 'msbuild.bzl')
        (self.work / 'BUILD.bazel').write_text('exports_files(["msbuild.bzl", "manifest.json", "replacement.txt"])\n')
        self.serial = 0

    def query(self, target, base='base', error=None):
        self.serial += 1
        output_base = self.evidence / base
        result = subprocess.run([str(BAZEL), '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_user_root=' + str(self.evidence / 'user'), '--output_base=' + str(output_base),
            'cquery', target, '--output=files', '--noshow_progress', '--color=no', '--curses=no'],
            cwd=self.work, text=True, capture_output=True, timeout=180)
        (self.work / f'query-{self.serial}.log').write_text(result.stdout + result.stderr)
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout + result.stderr)
            return {}
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # cquery source artifacts are rooted at output_base/external. Inspect the
        # materialized symlinks as well as declared labels; never execute stubs.
        return {line: (output_base / line).read_bytes() for line in result.stdout.splitlines() if line.startswith('external/')}

    def sdk(self, path, imports=None):
        (self.work / 'MODULE.bazel').write_text('local_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n' +
            'local_dotnet_sdk(name="dotnet", path=' + json.dumps(str(path)) + ', external_imports=' + json.dumps(imports or []) + ')\n')

    def runtime(self, manifest, overrides=None):
        (self.work / 'manifest.json').write_text(json.dumps(manifest))
        (self.work / 'MODULE.bazel').write_text('local_native_runtime = use_repo_rule("//:msbuild.bzl", "local_native_runtime")\n' +
            'local_native_runtime(name="native", manifest="//:manifest.json", overrides=' + json.dumps(overrides or {}) + ')\n')

    def test_sdk_redeclaration_refetch_and_invalid_import(self):
        for revision in ('first', 'second'):
            sdk = self.work / revision
            sdk.mkdir()
            (sdk / 'dotnet').write_text(revision)
            (sdk / (revision + '.txt')).write_text('declared ' + revision)
            self.sdk(sdk)
            files = self.query('@dotnet//:files')
            self.assertEqual(sorted(files.values()), sorted([revision.encode(), ('declared ' + revision).encode()]))
        fresh = self.query('@dotnet//:files', base='fresh-base')
        self.assertEqual(files, fresh)
        self.sdk(sdk, ['/private/tmp/undeclared.targets'])
        self.query('@dotnet//:files', error='external_imports require explicit Nix SDK import paths')

    def test_installed_sdk_exports_real_tool_files(self):
        sdk = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
        self.assertTrue((sdk / 'dotnet').is_file(), 'Install the pinned SDK before S05 acceptance')
        self.sdk(sdk)
        # Query labels instead of reading the entire SDK into memory.
        result = subprocess.run([str(BAZEL), '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_user_root=' + str(self.evidence / 'user'), '--output_base=' + str(self.evidence / 'base'),
            'cquery', '@dotnet//:files', '--output=files', '--noshow_progress'], cwd=self.work,
            capture_output=True, text=True, timeout=180)
        (self.work / 'installed-sdk.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('/sdk/dotnet\n', result.stdout)
        self.assertIn('/sdk/sdk/10.0.400/MSBuild.dll\n', result.stdout)

    def test_runtime_manifest_schema_and_override_rejections(self):
        self.runtime(dict(schemaVersion=1, files=[], storePaths=[]))
        self.query('@native//:files', error='native runtime manifest requires schemaVersion 2')
        (self.work / 'replacement.txt').write_text('replacement')
        self.runtime(dict(schemaVersion=2, files=[], storePaths=[]), {'//:replacement.txt': 'absent/lib.dylib'})
        self.query('@native//:files', error='native runtime override absent from manifest: absent/lib.dylib')

    def test_runtime_payload_override_and_manifest_refresh(self):
        store = self.work / 'store-root'
        store.mkdir()
        (store / 'first.dylib').write_text('original')
        manifest = dict(schemaVersion=2, files=[dict(path='store-root/first.dylib')], storePaths=[str(store)])
        self.runtime(manifest)
        initial = self.query('@native//:files')
        self.assertEqual(list(initial.values()), [b'original'])
        self.assertTrue(all(p.endswith('/store-root/first.dylib') for p in initial))
        (self.work / 'replacement.txt').write_text('replacement-v1')
        self.runtime(manifest, {'//:replacement.txt': 'store-root/first.dylib'})
        self.assertEqual(list(self.query('@native//:files').values()), [b'replacement-v1'])
        (self.work / 'replacement.txt').write_text('replacement-v2')
        self.assertEqual(list(self.query('@native//:files').values()), [b'replacement-v2'])
        # Change manifest membership at the same label/output base, remove the old
        # file, then compare with independently materialized external repo state.
        (store / 'first.dylib').unlink()
        (store / 'second.dylib').write_text('second')
        manifest['files'] = [dict(path='store-root/second.dylib')]
        self.runtime(manifest)
        changed = self.query('@native//:files')
        self.assertEqual(list(changed.values()), [b'second'])
        self.assertTrue(all(p.endswith('/store-root/second.dylib') for p in changed))
        self.assertEqual(changed, self.query('@native//:files', base='fresh-base'))


if __name__ == '__main__':
    unittest.main()
