"""Declared SDK account defaults and fail-fast identity checks."""
import ast
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from native_environment import sdk_account_check


class SdkAccountTests(unittest.TestCase):
    def declarations(self, sdk):
        rules = []
        archives = []
        namespace = {
            'native': SimpleNamespace(genrule=lambda **kw: rules.append(kw), filegroup=lambda **kw: None),
            'msbuild_native_toolchain_packages': lambda **kw: None,
            'pkg_tar': lambda **kw: archives.append(kw),
        }
        tree = ast.parse((ROOT / 'tests/runtime/native_inputs.bzl').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'native_toolchain_inputs')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'native_inputs.bzl', 'exec'), namespace)
        namespace['native_toolchain_inputs']('toolchain', {}, architecture='x64', sdk=sdk)
        return rules, archives[0]

    def test_sdk_archive_declares_real_line_delimited_account_files(self):
        rules, archive = self.declarations(True)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            contents = {}
            for rule in rules:
                if not rule['name'].startswith('sdk_'):
                    continue
                destination = output / rule['outs'][0]
                subprocess.run(['bash', '-c', rule['cmd'].replace('$@', shlex.quote(str(destination)))], check=True)
                contents[archive['files'][':' + rule['name']]] = destination.read_text()
            self.assertEqual(contents['etc/passwd'].splitlines(),
                             ['root:x:0:0:root:/tmp:/bin/bash', 'builder:x:1000:1000:Build user:/tmp:/bin/bash'])
            self.assertEqual(contents['etc/group'].splitlines(), ['root:x:0:', 'builder:x:1000:'])
            self.assertEqual(contents['etc/nsswitch.conf'], 'passwd: files\ngroup: files\nhosts: files dns\n')

    def test_runtime_archive_stays_independent_of_sdk_account_setup(self):
        rules, archive = self.declarations(False)
        self.assertEqual(rules, [])
        self.assertEqual(archive['files'], {})

    def test_guard_accepts_declared_accounts_and_rejects_other_host_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            scripts = {
                'id': '#!/bin/sh\nif [ "$1" = -u ]; then echo "$FIXTURE_UID"; else echo "$FIXTURE_GID"; fi\n',
                'getent': '#!/bin/sh\ncase "$2" in 0|1000) exit 0;; *) exit 2;; esac\n',
            }
            for name, content in scripts.items():
                path = folder / name
                path.write_text(content)
                path.chmod(0o755)
            for uid, gid, success in [('0', '0', True), ('1000', '1000', True), ('1001', '1000', False), ('1000', '1001', False)]:
                with self.subTest(uid=uid, gid=gid):
                    environment = dict(os.environ, PATH=str(folder), FIXTURE_UID=uid, FIXTURE_GID=gid)
                    result = subprocess.run(['/bin/bash', '-c', sdk_account_check()], env=environment,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode == 0, success)
                    if not success:
                        self.assertIn('declared defaults are root (0) and builder (1000)', result.stderr)


if __name__ == '__main__':
    unittest.main()
