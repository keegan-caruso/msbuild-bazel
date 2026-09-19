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
            event = dict(mnemonic='MsbuildCompileProject', runner='darwin-sandbox', cacheHit=False,
                commandArgs=['dotnet', 'réquête "\\.json'], inputs=[dict(path='long/source.cs')] * 100000,
                actualOutputs=[dict(path='bundle')], listedOutputs=['bundle'])
            second = dict(mnemonic='MsbuildComposeRuntime', runner='remote cache hit', cacheHit=True)
            payload = ('\n'.join(json.dumps(e, ensure_ascii=False) for e in [event, second])).encode()
            result = self.invoke(root, payload, exit_code=7)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '7', (root / 'process.log').read_text())
            self.assertEqual(gzip.decompress((root / 'execution.json.gz').read_bytes()), payload)
            summary = [json.loads(line) for line in (root / 'execution.json').read_text().splitlines()]
            for field in ['inputs', 'actualOutputs', 'listedOutputs']: event.pop(field)
            self.assertEqual(summary, [event, second])
            self.assertLess((root / 'execution.json').stat().st_size, 1000)

    def test_no_writer_and_missing_process_do_not_hang(self):
        for executable in [None, '/does/not/exist']:
            with tempfile.TemporaryDirectory() as folder:
                result = self.invoke(Path(folder), b'', executable=executable, writer=False)
                self.assertEqual(result.returncode == 0, executable is None, result.stderr)

    def test_malformed_trace_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.invoke(Path(folder), b'{"mnemonic":"ok"}\n{"broken":')
            self.assertNotEqual(result.returncode, 0)

    def test_capture_failure_does_not_block_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'execution.json.gz').mkdir()
            result = self.invoke(root, b' ' * 1000000)
            self.assertNotEqual(result.returncode, 0)
