"""Matrix selection must not turn an exact version check into a bypass."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from bazel_version import validate_version


class BazelVersionTests(unittest.TestCase):
    def test_exact_release_and_nixpkgs_label(self):
        for version in ('7.7.1', '8.4.2', '8.8.0', '9.2.0'):
            for suffix in ('', '- (@non-git)'):
                label = 'bazel ' + version + suffix
                self.assertEqual(validate_version('Starting server...\n' + label, version), label)

    def test_wrong_release_and_unrecognized_suffix_are_rejected(self):
        for output in ('bazel 8.4.2', 'bazel 9.2.0rc1', 'bazel 9.2.0-custom', ''):
            with self.assertRaisesRegex(ValueError, 'expected pinned Bazel 9.2.0'):
                validate_version(output, '9.2.0')
