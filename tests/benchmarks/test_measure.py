"""Regression checks for failed samples and independent benchmark inputs."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.measure import command
from benchmarks.run import summarize
from benchmarks.snapshot import snapshot


class Measurements(unittest.TestCase):
    def test_failed_process_is_retained(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'failed.log'
            result, seconds = command([sys.executable, '-c', 'print("failed"); raise SystemExit(7)'], folder, log)
            record = json.loads(log.with_suffix('.log.measurement.json').read_text())
            self.assertEqual(result.returncode, 7)
            self.assertEqual(record['exitCode'], 7)
            self.assertEqual(record['wallSeconds'], seconds)
            self.assertEqual(record['timingScope'], 'end-to-end')
            self.assertIn('failed', log.read_text())

    def test_timeout_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'timeout.log'
            with self.assertRaises(subprocess.TimeoutExpired):
                command([sys.executable, '-c', 'import time; time.sleep(10)'], folder, log, timeout=.05)
            self.assertIsNotNone(json.loads(log.with_suffix('.log.measurement.json').read_text())['failure'])

    def test_csv_requires_all_successful_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'raw.csv'
            def write(statuses):
                with path.open('w') as stream:
                    writer = csv.DictWriter(stream, fieldnames=['bazel_commit', 'wall', 'exit_status'])
                    writer.writeheader()
                    writer.writerows(dict(bazel_commit='bazel-9.2.0', wall=i+1, exit_status=s) for i, s in enumerate(statuses))
            write([0, 0, 0])
            self.assertEqual(summarize(path, 3, 1)['bazel-9.2.0']['medianSeconds'], 2)
            (Path(folder)/'benchmark.log').write_text('Bazel command failed with exit code 1')
            with self.assertRaises(RuntimeError):
                summarize(path, 3, 1)
            (Path(folder)/'benchmark.log').unlink()
            for statuses in [[0, 1, 0], [0, 0]]:
                write(statuses)
                with self.assertRaises(RuntimeError):
                    summarize(path, 3, 1)

    def test_snapshot_owns_input_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source'; source.mkdir()
            (source/'input.cs').write_text('original')
            (source/'Input.csproj').write_text('<Project />')
            (source/'bin').mkdir(); (source/'bin/output.dll').write_text('output')
            output = snapshot(source, Path(folder)/'snapshot')
            (source/'input.cs').write_text('changed')
            self.assertEqual((output/'input.cs').read_text(), 'original')
            self.assertFalse((output/'bin').exists())
            with self.assertRaises(ValueError):
                snapshot(source, source/'nested')
