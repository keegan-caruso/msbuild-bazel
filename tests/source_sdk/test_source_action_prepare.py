"""Controls for source SDK qualification's generated Bazel declarations."""
import ast
import hashlib
from acquire_x64 import verify
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import source_action_prepare

from source_action_prepare import platform_configuration, validate_bootstrap_host, write_bazel_files


class SourceActionTemplatesTests(unittest.TestCase):
    def test_generated_bazel_files_parse_and_keep_declared_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            rules = workspace / 'rules path "quoted"'
            write_bazel_files(workspace, rules)
            module = (workspace / 'MODULE.bazel').read_text()
            build = (workspace / 'BUILD.bazel').read_text()
            # These templates use the Python-compatible subset of Starlark.
            ast.parse(module, filename='MODULE.bazel')
            ast.parse(build, filename='BUILD.bazel')
            self.assertIn('path=' + json.dumps(str(rules)), module)
            self.assertIn('version="10.0.400"', module)
            for declaration in ('sources="sources.tar"', 'bootstrap="bootstrap.tar"',
                                'native_tools="native.tar"', 'name="smoke"'):
                self.assertIn(declaration, build)
            buildifier = os.environ.get('BUILDIFIER')
            if buildifier:
                for name in ('MODULE.bazel', 'BUILD.bazel'):
                    subprocess.run([buildifier, '-mode=fix', str(workspace / name)],
                                   stdout=subprocess.DEVNULL, check=True)

    def test_x64_requires_verified_declared_root_before_preparing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'native.tar'
            archive.write_bytes(b'changed')
            output = root / 'action'
            positional = ['source_action_prepare', str(root / 'source.tar.gz'), str(root / 'vmr'), str(output)]
            cases = [(['--architecture=x64'], 'requires declared native tools'),
                     (['--architecture=x64', '--native-tools=' + str(archive),
                       '--native-tools-sha256=' + '0' * 64], 'matching SHA256')]
            for options, message in cases:
                with patch.object(source_action_prepare.platform, 'system', return_value='Linux'), \
                        patch.object(source_action_prepare.platform, 'machine', return_value='x86_64'), \
                        patch('sys.argv', positional + options):
                    with self.assertRaisesRegex(ValueError, message):
                        source_action_prepare.main()
                self.assertFalse(output.exists())

    def test_acquired_bootstrap_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'sdk.tar.gz'
            archive.write_bytes(b'original')
            pin = {'bytes': 8, 'sha256': hashlib.sha256(b'original').hexdigest()}
            verify(archive, pin)
            archive.write_bytes(b'corrupt!')
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                verify(archive, pin)

    def test_bootstrap_elf_must_match_selected_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = Path(temporary) / 'dotnet'
            for architecture, machine in [('arm64', 183), ('x64', 62)]:
                host.write_bytes(b'\x7fELF\x02\x01' + b'\0' * 12 + machine.to_bytes(2, 'little'))
                validate_bootstrap_host(host, architecture)
                with self.assertRaises(ValueError):
                    validate_bootstrap_host(host, 'x64' if architecture == 'arm64' else 'arm64')

    def test_x64_declarations_select_native_platform(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            write_bazel_files(workspace, workspace / 'rules', 'x64', system_bwrap=True)
            module = (workspace / 'MODULE.bazel').read_text()
            build = (workspace / 'BUILD.bazel').read_text()
            ast.parse(module)
            ast.parse(build)
            self.assertIn('platform="linux-x64"', module)
            self.assertIn('dotnet.sdk_archive', module)
            self.assertIn('integrity="sha256-', module)
            self.assertIn('cpu:x86_64', build)
            self.assertIn('system_bwrap=True', build)
            self.assertIn('runtime_identifier="linux-x64"', build)
            self.assertNotIn('arm64', module + build)
        with self.assertRaises(ValueError):
            platform_configuration('amd64')


if __name__ == '__main__':
    unittest.main()
