"""Bounded execution trace capture preserves the original and fails closed."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ExecutionTrace(unittest.TestCase):
    def invoke(self, root, payload, *, executable=None, exit_code=0, writer=True):
        source = root / 'source'
        source.write_bytes(payload)
        script = root / 'writer.py'
        script.write_text('import os,pathlib,stat,sys\n'
            'for fd in range(3,256):\n'
            ' try: info=os.fstat(fd)\n'
            ' except OSError: continue\n'
            ' target=os.stat(sys.argv[1].split("=",1)[1])\n'
            ' assert (info.st_dev,info.st_ino)!=(target.st_dev,target.st_ino), "Inherited trace pipe"\n' + (
            'with open(sys.argv[1].split("=",1)[1],"wb") as out:\n'
            ' data=pathlib.Path("source").read_bytes()\n'
            ' for i in range(0,len(data),137): out.write(data[i:i+137])\n'
            if writer else '') + f'sys.exit({exit_code})\n')
        request = root / 'request.json'
        request.write_text(json.dumps(dict(executable=executable or sys.executable,
            arguments=[str(script), '--execution_log_json_file=' + str(root / 'execution.json')],
            cwd=str(root), log=str(root / 'process.log'))))
        return subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'),
            str(ROOT / 'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),
            'execute-trace', str(request)], capture_output=True, text=True, timeout=30)

    def test_large_records_round_trip_and_action_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def varint(n):
                data = bytearray()
                while n > 127: data.append((n & 127) | 128); n >>= 7
                data.append(n)
                return bytes(data)
            def string(field, text):
                data = text.encode()
                return varint(field * 8 + 2) + varint(len(data)) + data
            first = (string(1, 'dotnet') + string(1, 'réquête "\\.json') +
                string(10, 'MsbuildCompileProject') + string(12, 'darwin-sandbox') +
                string(4, 'long/source.cs' * 100000) + string(11, 'bundle'))
            second = string(10, 'MsbuildComposeRuntime') + string(12, 'remote cache hit') + varint(13*8) + b'\1'
            payload = varint(len(first)) + first + varint(len(second)) + second
            result = self.invoke(root, payload, exit_code=7)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '7', (root / 'process.log').read_text())
            self.assertEqual(gzip.decompress((root / 'execution.bin.gz').read_bytes()), payload)
            summary = [json.loads(line) for line in (root / 'execution.json').read_text().splitlines()]
            self.assertEqual(summary, [dict(commandArgs=['dotnet', 'réquête "\\.json'], cacheHit=False,
                exitCode=0, mnemonic='MsbuildCompileProject', runner='darwin-sandbox'),
                dict(commandArgs=[], cacheHit=True, exitCode=0, mnemonic='MsbuildComposeRuntime', runner='remote cache hit')])
            self.assertLess((root / 'execution.json').stat().st_size, 1000)

    def test_no_writer_and_missing_process_do_not_hang(self):
        for executable in [None, '/does/not/exist']:
            with tempfile.TemporaryDirectory() as folder:
                result = self.invoke(Path(folder), b'', executable=executable, writer=False)
                self.assertEqual(result.returncode == 0, executable is None, result.stderr)

    def test_malformed_trace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(Path(folder), b'\5\x52\3ab')
            self.assertNotEqual(result.returncode, 0)

    def test_capture_failure_does_not_block_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'execution.bin.gz').mkdir()
            result = self.invoke(root, b' ' * 1000000)
            self.assertNotEqual(result.returncode, 0)

    @unittest.skipUnless(os.environ.get('RULES_MSBUILD_BAZEL'), 'pinned Bazel required')
    def test_real_bazel_retains_executed_action(self):
        bazel = os.environ['RULES_MSBUILD_BAZEL']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'MODULE.bazel').write_text('module(name="trace_test")\n')
            (root / 'BUILD.bazel').write_text('genrule(name="probe", outs=["out"], cmd="echo trace > $@")\n')
            startup = ['--nosystem_rc', '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(root / 'state')]
            request = root / 'request.json'
            request.write_text(json.dumps(dict(executable=bazel, arguments=startup + ['build', '//:probe',
                '--incompatible_autoload_externally=', '--execution_log_json_file=' + str(root / 'execution.json')],
                cwd=str(root), log=str(root / 'bazel.log'))))
            try:
                result = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'),
                    str(ROOT / 'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),
                    'execute-trace', str(request)], capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), '0', (root / 'bazel.log').read_text())
                actions = [json.loads(line) for line in (root / 'execution.json').read_text().splitlines()]
                self.assertEqual(len(actions), 1, actions)
                self.assertEqual(actions[0]['mnemonic'], 'Genrule')
                self.assertTrue(actions[0]['commandArgs'])
                self.assertFalse(actions[0]['cacheHit'])
                self.assertGreater(len(gzip.decompress((root / 'execution.bin.gz').read_bytes())), 100)
            finally:
                subprocess.run([bazel] + startup + ['shutdown'], cwd=root, capture_output=True, timeout=30)
