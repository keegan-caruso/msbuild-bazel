import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from probe_mvp_package_inputs import capture_process_output, rejection_diagnostic


class PackageRejectionTests(unittest.TestCase):
    def test_unrelated_build_failure_is_not_package_rejection(self):
        error = subprocess.CalledProcessError(1, ['dotnet', 'build', 'GraphExport'])
        with self.assertRaises(AssertionError):
            rejection_diagnostic(error, ('hash-mismatch',), 'hash-mismatch')

    def test_exporter_failure_requires_expected_diagnostic(self):
        error = subprocess.CalledProcessError(1, ['dotnet', '/tools/GraphExport.dll'])
        with self.assertRaises(AssertionError):
            rejection_diagnostic(error, ('hash-mismatch',), 'unrelated exporter failure')
        self.assertIn('hash-mismatch', rejection_diagnostic(error, ('hash-mismatch',), 'hash-mismatch: package payload'))

    def test_capture_inherited_subprocess_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'output.log'
            with capture_process_output(path):
                subprocess.run([sys.executable, '-c', 'import os; os.write(1,b"out"); os.write(2,b"err")'], check=True)
            self.assertEqual(path.read_text(), 'outerr')
