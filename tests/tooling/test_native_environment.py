"""Native runtime producers select their compiler inside the declared root."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import copy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from source_runtime.native import declare_inputs
from native_environment import build_prefix, load_catalog, LLVM_MAJOR, LLVM_VERSION


class NativeEnvironmentTests(unittest.TestCase):
    def test_every_product_script_checks_declared_distribution_and_compiler(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            workspace = base / 'workspace'
            workspace.mkdir()
            (workspace / 'MODULE.bazel').write_text('module(name="fixture")\n')
            preparation = base / 'preparation'
            preparation.mkdir()
            (preparation / 'inputs.json').write_text(json.dumps({
                'source': {'urls': ['https://example.invalid/source.tar.gz'], 'sha256': 'a' * 64, 'commit': 'b' * 40},
                'packages': [{'name': 'clang-18', 'url': 'https://example.invalid/clang.deb', 'sha256': 'c' * 64}]}))
            provenance = declare_inputs(workspace, preparation)
            self.assertEqual(provenance['kind'], 'packages')
            self.assertEqual(provenance['timezone'], 'Etc/UTC')
            self.assertEqual(provenance['compilerVersion'], '18.1.8')
            for component in ['coreclr', 'libraries', 'host']:
                script = workspace / 'native' / (component + '.sh')
                body = script.read_text()
                self.assertTrue(body.startswith(build_prefix()))
                self.assertIn('-clang18 -arm64', body)
                self.assertIn('test "$ID/$VERSION_ID" = ubuntu/26.04', body)
                self.assertIn('export CC=clang-18 CXX=clang++-18', body)
                self.assertIn('export PATH=/usr/lib/llvm-18/bin:$PATH', body)
                self.assertIn(f'clang version {LLVM_VERSION}', body)
                subprocess.run(['bash', '-n', str(script)], check=True)

    def test_native_catalogs_match_selected_architecture_and_compiler(self):
        for architecture, deb_architecture in [('arm64', 'arm64'), ('x64', 'amd64')]:
            value = load_catalog(architecture)
            self.assertEqual(value['platform'], 'linux-' + architecture)
            self.assertTrue(all(item['architecture'] in (deb_architecture, 'all') for item in value['packages']))
            self.assertFalse({item['name'] for item in value['packages']} & {'rust-coreutils', 'coreutils-from-uutils'})
        script = build_prefix('x64')
        self.assertIn('test "$(uname -m)" = x86_64', script)
        self.assertIn('^x86_64-.*linux-gnu$', script)
        subprocess.run(['bash', '-n'], input=script, text=True, check=True)
        with self.assertRaises(ValueError):
            build_prefix('amd64')
        with self.assertRaises(ValueError):
            load_catalog('amd64')

    def test_native_catalog_rejects_mixed_architecture_and_changed_identity(self):
        original = load_catalog('x64')
        for field, value in [('architecture', 'arm64'), ('sha256', 'invalid'),
                             ('url', 'https://example.invalid/package.deb')]:
            changed = copy.deepcopy(original)
            changed['packages'][0][field] = value
            with patch.object(Path, 'read_text', return_value=json.dumps(changed)):
                with self.assertRaises(ValueError):
                    load_catalog('x64')
        changed = copy.deepcopy(original)
        next(item for item in changed['packages'] if item['name'] == 'clang-18')['version'] = '18.0'
        with patch.object(Path, 'read_text', return_value=json.dumps(changed)):
            with self.assertRaises(ValueError):
                load_catalog('x64')
        aliases = (ROOT / 'tests/runtime/native_inputs.bzl').read_text()
        self.assertIn('"lib64": "usr/lib64"', aliases)

    def test_aliases_resolve_to_selected_family_without_default_compiler(self):
        aliases = (ROOT / 'tests/runtime/native_inputs.bzl').read_text()
        self.assertIn('"etc/localtime": "usr/share/zoneinfo/Etc/UTC"', aliases)
        for name in ['clang', 'clang++', 'ld.lld', 'llvm-ar', 'llvm-objcopy', 'llvm-strip']:
            self.assertIn(f'"usr/bin/{name}": "usr/bin/{name}-{LLVM_MAJOR}"', aliases)
        dockerfile = (ROOT / 'containers/runtime-demo.Dockerfile').read_text()
        for name in ['clang-18', 'lld-18', 'llvm-18', 'libclang-rt-18-dev']:
            self.assertIn(name + '=1:18.1.8-20ubuntu8', dockerfile)
        self.assertNotIn('clang clang-', dockerfile)
        self.assertNotIn('build-essential', dockerfile)
        catalog = json.loads((ROOT / 'tests/runtime/native-packages.json').read_text())
        names = {package['name'] for package in catalog['packages']}
        self.assertEqual(catalog['distribution'], 'ubuntu-26.04')
        self.assertIn('coreutils-from-gnu', names)
        self.assertFalse(names & {'rust-coreutils', 'coreutils-from-uutils', 'clang', 'lld', 'llvm'})
        for name in ['clang-18', 'lld-18', 'llvm-18', 'libclang-rt-18-dev']:
            package = next(package for package in catalog['packages'] if package['name'] == name)
            self.assertEqual(package['version'], '1:18.1.8-20ubuntu8')


if __name__ == '__main__':
    unittest.main()
