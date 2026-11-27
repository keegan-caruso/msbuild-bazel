"""Same-byte system launcher selection never silently changes sandbox tools."""
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tests/runtime'))
import system_bwrap


class SystemBwrapTests(unittest.TestCase):
    def test_default_preserves_declared_launcher_without_host_reads(self):
        with patch.object(Path, 'lstat', side_effect=AssertionError('host read')):
            self.assertEqual(system_bwrap.select_sandbox(Path('/declared')), Path('/declared'))

    @unittest.skipIf(os.name == 'nt', 'Linux Bubblewrap selection requires POSIX executable bits')
    def test_explicit_handoff_checks_bytes_and_privileged_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            declared = Path(temporary)/'declared'; declared.write_bytes(b'pinned bwrap')
            host = Path(temporary)/'system'; host.write_bytes(declared.read_bytes()); host.chmod(0o755)
            trusted = SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)
            with patch.object(system_bwrap.sys, 'platform', 'linux'), \
                 patch.object(system_bwrap, 'SYSTEM_BWRAP', host), patch.object(Path, 'lstat', return_value=trusted):
                self.assertEqual(system_bwrap.select_sandbox(declared, True), host)
                host.write_bytes(b'different installed package')
                with self.assertRaisesRegex(ValueError, 'SHA-256 differs.*Install the pinned'):
                    system_bwrap.select_sandbox(declared, True)
                for mode, uid in [(stat.S_IFLNK | 0o755, 0), (stat.S_IFREG | 0o775, 0), (stat.S_IFREG | 0o755, 1000)]:
                    with self.subTest(mode=mode, uid=uid), patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_uid=uid)):
                        with self.assertRaisesRegex(ValueError, 'root-owned'):
                            system_bwrap.select_sandbox(declared, True)
            with patch.object(system_bwrap.sys, 'platform', 'darwin'):
                with self.assertRaisesRegex(ValueError, 'requires Linux'):
                    system_bwrap.select_sandbox(declared, True)


if __name__ == '__main__':
    unittest.main()
