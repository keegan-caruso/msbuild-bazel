"""Native runtime producers select their compiler inside the declared root."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from source_runtime.native import declare_inputs
from native_environment import build_prefix, LLVM_MAJOR, LLVM_VERSION


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

    def test_aliases_resolve_to_selected_family_without_default_compiler(self):
        aliases = (ROOT / 'tests/runtime/native_inputs.bzl').read_text()
        for name in ['clang', 'clang++', 'ld.lld', 'llvm-ar', 'llvm-objcopy', 'llvm-strip']:
            self.assertIn(f'"usr/bin/{name}": "usr/bin/{name}-{LLVM_MAJOR}"', aliases)
        dockerfile = (ROOT / 'containers/runtime-demo.Dockerfile').read_text()
        self.assertIn('clang-18 lld-18 llvm-18', dockerfile)
        self.assertNotIn('clang clang-', dockerfile)
        self.assertNotIn('build-essential', dockerfile)
        catalog = json.loads((ROOT / 'tests/runtime/native-packages.json').read_text())
        names = {package['name'] for package in catalog['packages']}
        self.assertEqual(catalog['distribution'], 'ubuntu-26.04')
        self.assertIn('coreutils-from-gnu', names)
        self.assertFalse(names & {'rust-coreutils', 'coreutils-from-uutils', 'clang', 'lld', 'llvm'})
        for name in ['clang-18', 'lld-18', 'llvm-18']:
            package = next(package for package in catalog['packages'] if package['name'] == name)
            self.assertEqual(package['version'], '1:18.1.8-20ubuntu8')


if __name__ == '__main__':
    unittest.main()
