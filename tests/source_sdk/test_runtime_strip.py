"""Verify the derivative strips only ELF files and preserves debug inputs/modes."""
import ast
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest


class RuntimeStripTests(unittest.TestCase):
    def test_actual_action_keeps_inputs_and_non_elf_files(self):
        source = Path(__file__).with_name('runtime_strip.bzl').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef))
        calls = []
        runtime = SimpleNamespace(directory=SimpleNamespace(path='debug'), files=['debug'],
                                  entry_point='dotnet', launch_mode='dotnet',
                                  runtime_identifier='linux-arm64', version='11.0.0', environment={})
        class RuntimeProvider:
            def __call__(self, **fields):
                return fields
        provider = RuntimeProvider()
        toolchain = SimpleNamespace(all_files=['declared-strip'], strip_executable='./strip')
        namespace = dict(MSBuildRuntimeInfo=provider, find_cpp_toolchain=lambda ctx: toolchain,
                         depset=list, DefaultInfo=lambda **fields: fields)
        ctx = SimpleNamespace(attr=SimpleNamespace(runtime={provider: runtime}), label=SimpleNamespace(name='lean'),
                              actions=SimpleNamespace(declare_directory=lambda name: SimpleNamespace(path=name),
                                                      run_shell=lambda **kw: calls.append(kw)))
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'runtime_strip.bzl', 'exec'), namespace)
        namespace['_stripped_runtime'](ctx)
        action = calls[0]
        self.assertEqual(action['tools'], ['declared-strip'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            debug = root / 'debug'
            (debug / 'shared').mkdir(parents=True)
            payloads = {'dotnet': b'\x7fELFdebug', 'shared/runtime.so': b'\x7fELFdebug',
                        'shared/managed.dll': b'MZdebug', 'shared/managed.pdb': b'debug'}
            for name, data in payloads.items():
                file = debug / name
                file.write_bytes(data)
                file.chmod(0o555 if name == 'dotnet' else 0o444)
            # Bazel may pre-create the declared output tree.
            (root / 'lean.runtime').mkdir()
            strip = root / 'strip'
            strip.write_text('#!/usr/bin/env python3\nimport pathlib,sys\n'
                             'assert sys.argv[1:3] == ["--strip-debug", "-o"]\n'
                             'pathlib.Path(sys.argv[3]).write_bytes(pathlib.Path(sys.argv[4]).read_bytes()[:4])\n')
            strip.chmod(0o755)
            subprocess.run(['bash', '-c', action['command'], '--', *action['arguments']], cwd=root, check=True)
            for name, data in payloads.items():
                self.assertEqual((debug / name).read_bytes(), data)
                result = root / 'lean.runtime' / name
                self.assertEqual(result.read_bytes(), data[:4] if data.startswith(b'\x7fELF') else data)
                self.assertEqual(result.stat().st_mode & 0o777, (debug / name).stat().st_mode & 0o777)
            self.assertFalse((root / 'lean.runtime/debug').exists())


if __name__ == '__main__':
    unittest.main()
