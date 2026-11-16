"""Portable controls for the source-runtime trial harness."""
import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'tests/graph_build/upstream/runtime_source_trials.py'
spec = importlib.util.spec_from_file_location('runtime_source_trials', SCRIPT)
trials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trials)


class RuntimeSourceTrialTests(unittest.TestCase):
    def test_replacement_breaks_hardlink_and_restores_mode_and_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, linked = root/'source.cs', root/'retained.cs'
            source.write_bytes(b'original')
            source.chmod(0o751)
            os.utime(source, ns=(1_600_000_000_000_000_000, 1_600_000_001_000_000_000))
            os.link(source, linked)
            original = source.stat()
            trials.replace_input(source, b'edited')
            self.assertNotEqual(source.stat().st_ino, linked.stat().st_ino)
            self.assertEqual(linked.read_bytes(), b'original')
            self.assertEqual(source.read_bytes(), b'edited')
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o751)
            trials.replace_input(source, b'original', original)
            restored = source.stat()
            self.assertEqual(stat.S_IMODE(restored.st_mode), 0o751)
            self.assertEqual((restored.st_atime_ns, restored.st_mtime_ns),
                             (original.st_atime_ns, original.st_mtime_ns))
            self.assertEqual(source.read_bytes(), b'original')
            self.assertEqual(linked.read_bytes(), b'original')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['retained.cs', 'source.cs'])

    def test_cli_help_exposes_oracle_and_mappings(self):
        output = subprocess.check_output([sys.executable, str(SCRIPT), '--help'], text=True)
        self.assertIn('--oracle', output)
        self.assertIn('--qualification-mappings', output)
        self.assertIn('--expected-mappings-sha256', output)


if __name__ == '__main__':
    unittest.main()
