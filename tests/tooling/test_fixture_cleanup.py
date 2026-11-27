"""Owned fixture deletion handles long Windows trees without changing tool paths."""
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_build'))
import fixture_host


class FixtureCleanupTests(unittest.TestCase):
    def test_windows_extended_paths(self):
        with patch.object(fixture_host, 'WINDOWS', True):
            self.assertEqual(fixture_host._cleanup_path(r'C:\fixture\tree'), '\\\\?\\C:\\fixture\\tree')
            self.assertEqual(fixture_host._cleanup_path(r'\\host\share\tree'), '\\\\?\\UNC\\host\\share\\tree')
            extended = '\\\\?\\C:\\fixture\\tree'
            self.assertEqual(fixture_host._cleanup_path(extended), extended)

    def test_long_readonly_tree_is_removed(self):
        with fixture_host.temporary_directory(prefix='fixture-cleanup-') as root:
            self.assertFalse(root.startswith('\\\\?\\'))
            leaf = Path(fixture_host._cleanup_path(root)).joinpath(*(['long directory ' + 'x' * 70] * 4), 'file.txt')
            self.assertGreater(len(str(leaf)), 300)
            leaf.parent.mkdir(parents=True)
            leaf.write_bytes(b'owned output')
            leaf.chmod(stat.S_IREAD)
        self.assertFalse(Path(root).exists())

    def test_cleanup_does_not_follow_directory_symlink(self):
        with tempfile.TemporaryDirectory(prefix='fixture-sibling-') as sibling:
            marker = Path(sibling, 'keep.txt')
            marker.write_text('unrelated')
            with fixture_host.temporary_directory(prefix='fixture-links-') as root:
                try:
                    Path(root, 'outside').symlink_to(sibling, target_is_directory=True)
                except OSError as error:
                    self.skipTest('Directory symlink creation unavailable: ' + str(error))
            self.assertEqual(marker.read_text(), 'unrelated')

    def test_cleanup_failure_is_visible_and_path_is_unchanged_for_body(self):
        temporary = Mock(name='temporary')
        temporary.name = os.path.abspath('ordinary-fixture')
        original = temporary.name
        temporary.cleanup.side_effect = PermissionError('owned cleanup failed')
        with patch.object(fixture_host.tempfile, 'TemporaryDirectory', return_value=temporary):
            with self.assertRaisesRegex(PermissionError, 'owned cleanup failed'):
                with fixture_host.temporary_directory(prefix='fixture-failure-') as root:
                    self.assertEqual(root, original)
                    self.assertEqual(temporary.name, original)
        temporary.cleanup.assert_called_once_with()
        self.assertEqual(temporary.name, fixture_host._cleanup_path(original))


if __name__ == '__main__':
    unittest.main()
