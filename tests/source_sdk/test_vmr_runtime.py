"""Reject unverified standalone runtime archives before SDK execution."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vmr_runtime


class StandaloneInputTests(unittest.TestCase):
    def invoke(self, root, options):
        arguments = ['vmr_runtime', '--sdk', str(root / 'missing-sdk'),
                     '--vmr-revision', 'revision', *options, str(root / 'output')]
        with patch('sys.argv', arguments), contextlib.redirect_stderr(io.StringIO()):
            vmr_runtime.main()

    def test_archive_requires_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SystemExit):
                self.invoke(root, ['--runtime-archive', str(root / 'archive')])
            self.assertFalse((root / 'output').exists())

    def test_digest_requires_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SystemExit):
                self.invoke(root, ['--runtime-sha256', '0' * 64])
            self.assertFalse((root / 'output').exists())

    def test_wrong_digest_rejects_before_sdk_or_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'archive'
            archive.write_bytes(b'not a runtime archive')
            with self.assertRaisesRegex(ValueError, 'archive digest differs'):
                self.invoke(root, ['--runtime-archive', str(archive), '--runtime-sha256', '0' * 64])
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
