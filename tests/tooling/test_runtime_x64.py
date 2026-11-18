"""Architecture closure for the native Linux source-runtime entry point."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from source_runtime.common import read_recipe
from source_runtime import native
sys.path.insert(0, str(ROOT/'tests/graph_build/upstream'))
from runtime_product_declarations import declare_product


class RuntimeArchitectureTests(unittest.TestCase):
    def test_sdk_recipes_bind_each_platform_and_same_source(self):
        arm, x64 = read_recipe(), read_recipe('x64')
        self.assertEqual(arm['source'], x64['source'])
        self.assertEqual(x64['platform'], 'linux-x64')
        pins = json.loads((ROOT/'scripts/toolchains.json').read_text())['dotnet']
        self.assertEqual(x64['sdk']['urls'], [pins['url']])
        self.assertEqual(x64['sdk']['sha256'], pins['sha256'])
        with self.assertRaisesRegex(ValueError, 'architecture'):
            read_recipe('riscv64')

    def test_managed_contracts_translate_architecture_and_preserve_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            mappings = []
            for architecture in ('arm64', 'x64'):
                output = Path(temporary)/architecture
                subprocess.run([sys.executable, str(ROOT/'tests/graph_build/upstream/runtime_contract.py'),
                    str(output), '--platform=linux-' + architecture, '--prepared-restore', '--resolve-references'], check=True)
                mappings.append(json.loads(output.read_text()))
            arm, x64 = mappings
            self.assertEqual(x64['projectDefaults']['properties']['TargetArchitecture'], 'x64')
            self.assertEqual(set(arm['projects']), set(x64['projects']))
            self.assertEqual(json.loads(json.dumps(arm).replace('arm64', 'x64')), x64)

    def test_product_composition_rejects_mixed_architectures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'inputs.json').write_text(json.dumps({'architecture': 'arm64'}))
            with self.assertRaisesRegex(ValueError, 'architectures differ'):
                declare_product(root, root, {'platform': 'linux-x64'})

    def test_declared_native_commands_and_inputs_close_selected_architecture(self):
        for architecture in ('arm64', 'x64'):
            with self.subTest(architecture=architecture), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root/'source.tar'; source.write_bytes(b'source')
                recipe = read_recipe(architecture)
                recipe['source']['sha256'] = native.digest(source)
                preparation = root/'preparation'
                with patch.object(native, 'read_recipe', return_value=recipe), \
                     patch.object(native, 'load_catalog', return_value={'packages': [dict(name='tool', url='https://example.invalid/tool.deb', sha256='a'*64)]}):
                    native.prepare_inputs(preparation, source, architecture=architecture)
                workspace = root/'workspace'; workspace.mkdir()
                (workspace/'MODULE.bazel').write_text('')
                native.declare_inputs(workspace, preparation)
                self.assertEqual(json.loads((preparation/'inputs.json').read_text())['architecture'], architecture)
                build = (workspace/'native/BUILD.bazel').read_text()
                self.assertIn('architecture="' + architecture + '"', build)
                core = (workspace/'native/coreclr.sh').read_text()
                self.assertIn('-' + architecture + ' -release', core)
                self.assertIn('linux.' + architecture + '.Release/', core)
                self.assertIn('linux-' + architecture + '.Release/corehost/', (workspace/'native/host.sh').read_text())
                self.assertNotIn('arm64' if architecture == 'x64' else 'x86_64', core)


if __name__ == '__main__':
    unittest.main()
