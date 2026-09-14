"""Guard against loading a stale net10 artifact after a net11 tool build."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import msbuild_tool


class ToolOutputTests(unittest.TestCase):
    def test_uses_reported_output_amid_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stale = root / 'net10.0/ReplayPlugin.dll'
            selected = root / 'net11.0/ReplayPlugin.dll'
            for path in (stale, selected):
                path.parent.mkdir()
                path.write_bytes(b'tool')
            output = 'diagnostic {not JSON}\n' + json.dumps({'Properties': {
                'TargetFramework': 'net11.0', 'TargetPath': str(selected)}})
            self.assertEqual(msbuild_tool.output_path(output, 'ReplayPlugin'), selected)
            selected.unlink()
            with self.assertRaisesRegex(ValueError, 'missing or invalid'):
                msbuild_tool.output_path(output, 'ReplayPlugin')

    def test_does_not_accept_an_unrelated_dll(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Unrelated.dll'
            path.write_bytes(b'tool')
            output = json.dumps({'Properties': {'TargetFramework': 'net10.0', 'TargetPath': str(path)}})
            with self.assertRaisesRegex(ValueError, 'missing or invalid'):
                msbuild_tool.output_path(output, 'ReplayPlugin')


if __name__ == '__main__':
    unittest.main()
