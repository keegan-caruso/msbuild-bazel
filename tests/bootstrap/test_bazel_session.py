"""Server lifetime must not leak across probes, including failed probes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from bazel_session import BazelSession


class BazelSessionTests(unittest.TestCase):
    def test_server_reuse_and_shutdown_of_each_output_base(self):
        with tempfile.TemporaryDirectory() as output, patch.dict(os.environ, RULES_MSBUILD_BAZEL_MODE='server'):
            with patch('bazel_session.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
                with BazelSession(output) as session:
                    for base in ('first', 'first', 'second'):
                        command = session.prepare(['bazel', '--batch', f'--output_base={base}', 'build', '//:app'], output, {})
                        self.assertNotIn('--batch', command)
                self.assertEqual(run.call_count, 2)
                self.assertTrue(all(call.args[0][-1] == 'shutdown' for call in run.call_args_list))

    def test_batch_does_not_start_or_stop_servers(self):
        with tempfile.TemporaryDirectory() as output, patch.dict(os.environ, RULES_MSBUILD_BAZEL_MODE='batch'):
            with patch('bazel_session.subprocess.run') as run:
                with BazelSession(output) as session:
                    command = ['bazel', '--batch', 'version']
                    self.assertEqual(session.prepare(command, output, {}), command)
                run.assert_not_called()

    def test_probe_failure_still_shuts_down(self):
        with tempfile.TemporaryDirectory() as output, patch.dict(os.environ, RULES_MSBUILD_BAZEL_MODE='server'):
            with patch('bazel_session.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '')) as run:
                with self.assertRaisesRegex(ValueError, 'probe failed'):
                    with BazelSession(output) as session:
                        session.prepare(['bazel', '--batch', 'build', '//:app'], output, {})
                        raise ValueError('probe failed')
                run.assert_called_once()

    def test_shutdown_failure_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as output, patch.dict(os.environ, RULES_MSBUILD_BAZEL_MODE='server'):
            with patch('bazel_session.subprocess.run', return_value=subprocess.CompletedProcess([], 1, 'failure')):
                with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                    with BazelSession(output) as session:
                        session.prepare(['bazel', '--batch', 'version'], output, {})
