"""Check the explicit launcher handoff in the native-root sealed probe."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('native_assembly', ROOT / 'scripts/assemble-native-toolchain.py')
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)


class NativeAssemblyTests(unittest.TestCase):
    def test_default_probe_keeps_the_declared_launcher(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(assembly.subprocess, 'run'):
            output = Path(temporary)
            command = assembly.probe(output, 'x64', sdk=True)
            self.assertEqual(command[0], str(output / 'bwrap'))
            self.assertIn('--unshare-all', command)

    def test_explicit_probe_uses_the_verified_policy_selection(self):
        select = Mock(return_value=Path('/usr/bin/bwrap'))
        policy = types.SimpleNamespace(select_sandbox=select)
        with tempfile.TemporaryDirectory() as temporary, patch.object(assembly.subprocess, 'run'), patch.dict('sys.modules', system_bwrap=policy):
            output = Path(temporary)
            command = assembly.probe(output, 'x64', sdk=True, system_bwrap=True)
            select.assert_called_once_with(output / 'bwrap', system_bwrap=True)
            self.assertEqual(command[0], str(Path('/usr/bin/bwrap')))
            self.assertIn('--unshare-all', command)


if __name__ == '__main__':
    unittest.main()
