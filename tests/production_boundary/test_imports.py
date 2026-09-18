"""Production entry points must not load experiment or test modules."""
import subprocess
import sys
import unittest
from pathlib import Path


class ProductionBoundary(unittest.TestCase):
    def test_imports_exclude_harness(self):
        root = Path(__file__).resolve().parents[2]
        result = subprocess.run([sys.executable, '-c', "import native_workflow; import sys; assert not any(n.startswith(('probe_', 'test_')) for n in sys.modules), sorted(sys.modules)"], cwd=root / 'tools', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
