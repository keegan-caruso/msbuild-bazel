"""Runtime launch-mode boundary independent of host acquisition."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))


class RuntimeHost(unittest.TestCase):
    def launch(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'app').mkdir()
            for name in ('.rules-msbuild-packages.json', '.rules-msbuild-package-files.json'):
                (root/'app'/name).write_text('{}')
            (root/'host').mkdir()
            host = root/'host/launch'
            host.write_text('#!/bin/sh\nprintf "%s\\n" "$CORE_ROOT" "$DOTNET_ROOT" "$MARKER" "$1" "$2"\n')
            host.chmod(0o755)
            request = dict(entry='app', dependencies=[], assembly='App', test=False, data=[],
                           runtimeHost=dict(directory='host', entryPoint='launch', launchMode=mode, environment={'MARKER': 'declared'}))
            (root/'launch.json').write_text(json.dumps(request))
            env = dict(os.environ, RULES_MSBUILD_RUNFILES=str(root), CORE_ROOT='/ambient')
            result = subprocess.run([str(SDK/'dotnet'), str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'),
                                     'run', str(root/'launch.json'), 'user-argument'], env=env, text=True, capture_output=True)
            return result, str(root/'host')

    def test_corerun_sets_core_root(self):
        result, host = self.launch('corerun')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = result.stdout.splitlines()
        self.assertEqual(rows[:3], [host, host, 'declared'])
        self.assertTrue(rows[3].endswith('/App.dll'))
        self.assertEqual(rows[4], 'user-argument')

    def test_dotnet_clears_ambient_core_root(self):
        result, host = self.launch('dotnet')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[:3], ['', host, 'declared'])

    def test_unknown_mode_fails(self):
        result, _ = self.launch('unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported runtime launch mode', result.stderr)
