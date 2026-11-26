"""Execute emitted bootstrap commands with a recording SDK host.

Windows path conversion is exercised with shell shims; native execution remains
part of Windows qualification rather than a claim made by these portable tests.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class BootstrapPaths(unittest.TestCase):
    def bootstrap(self, windows, path_map):
        namespace = {}
        tree = ast.parse((ROOT / 'msbuild/private/sdk_bootstrap.bzl').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'bootstrap_project')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'sdk_bootstrap.bzl', 'exec'), namespace)
        with tempfile.TemporaryDirectory(prefix='sdk-bootstrap-') as temporary:
            folder = Path(temporary).resolve()
            dotnet = folder / 'SDK with spaces/dotnet.exe'
            dotnet.parent.mkdir()
            dotnet.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
home=os.environ['DOTNET_CLI_HOME'].removeprefix('C:/mapped')
Path(os.environ['RECEIPT']).write_text(json.dumps({'args':sys.argv[1:],'env':dict(os.environ),'restoreConfig':Path(home,'NuGet.Config').read_text()}))
''')
            dotnet.chmod(0o755)
            captured = {}
            ctx = SimpleNamespace(actions=SimpleNamespace(run_shell=lambda **kw: captured.update(kw)))
            project = 'repository with spaces/tools/Tool/Tool.csproj'
            output = SimpleNamespace(path='output with spaces/tool.dll', dirname='output with spaces', is_directory=False)
            namespace['bootstrap_project'](ctx, SimpleNamespace(path=str(dotnet.relative_to(folder))),
                SimpleNamespace(path=project), [], [output], 'TestBootstrap', private_home=not path_map, path_map=path_map)
            prefix = ''
            if windows:
                prefix = '''uname() { printf '%s\\n' MINGW64_NT; }
cygpath() { test "$1" = -am; printf 'C:/mapped%s\\n' "$2"; }
'''
            receipt = folder / 'receipt.json'
            environment = dict(os.environ, RECEIPT=str(receipt))
            environment.pop('MSYS2_ARG_CONV_EXCL', None)
            subprocess.run(['bash', '-c', prefix + captured['command'], '--', *captured['arguments']],
                           cwd=folder, env=environment, check=True, capture_output=True, text=True, timeout=30)
            data = json.loads(receipt.read_text())
            native_prefix = 'C:/mapped' if windows else ''
            arguments = data['args']
            self.assertEqual(arguments[:2], ['build', native_prefix + str(folder / project)])
            self.assertEqual(arguments[arguments.index('-o') + 1], native_prefix + str(folder / 'output with spaces'))
            self.assertEqual(data['env']['DOTNET_ROOT'], native_prefix + str(dotnet.parent))
            scratch = data['env']['DOTNET_CLI_HOME']
            self.assertTrue(scratch.startswith(native_prefix + '/'), scratch)
            self.assertIn('-p:BaseIntermediateOutputPath=' + scratch + '/obj/', arguments)
            self.assertIn('-p:RestoreSources=' + scratch + '/empty', arguments)
            self.assertIn('-p:RestoreConfigFile=' + scratch + '/NuGet.Config', arguments)
            config = ET.fromstring(data['restoreConfig'])
            self.assertIsNotNone(config.find('packageSources/clear'))
            self.assertIsNotNone(config.find('fallbackPackageFolders/clear'))
            if windows:
                self.assertEqual(data['env']['MSYS2_ARG_CONV_EXCL'], '*')
                self.assertEqual(data['env']['USERPROFILE'], scratch)
                self.assertEqual(data['env']['APPDATA'], scratch + '/appdata')
                self.assertEqual(data['env']['LOCALAPPDATA'], scratch + '/localappdata')
                self.assertEqual(data['env']['PROGRAMFILES'], scratch + '/programfiles')
                self.assertEqual(data['env']['NUGET_PACKAGES'], scratch + '/packages')
                for name in ['TEMP', 'TMP', 'SystemTemp']:
                    self.assertEqual(data['env'][name], scratch)
            self.assertEqual(data['env']['DOTNET_ADD_GLOBAL_TOOLS_TO_PATH'], 'false')
            self.assertEqual(data['env']['DOTNET_GENERATE_ASPNET_CERTIFICATE'], 'false')
            self.assertEqual(data['env']['DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE'], 'true')
            if path_map:
                self.assertIn('-p:PathMap=' + native_prefix + str(folder / 'repository with spaces') +
                              '=/_/rules_msbuild%2C' + scratch + '=/_/bootstrap', arguments)
            else:
                self.assertEqual(data['env']['HOME'], scratch)
                self.assertEqual(data['env']['NUGET_PACKAGES'], scratch + '/packages')

    def test_unix_paths_and_spaces(self):
        for path_map in [False, True]:
            with self.subTest(path_map=path_map):
                self.bootstrap(False, path_map)

    def test_windows_native_paths_and_spaces(self):
        for path_map in [False, True]:
            with self.subTest(path_map=path_map):
                self.bootstrap(True, path_map)


class RuntimeResponseFiles(unittest.TestCase):
    def test_lf_and_crlf_preserve_spaced_paths(self):
        namespace = {
            'DefaultInfo': lambda **kw: SimpleNamespace(**kw),
            'MSBuildRuntimeInfo': lambda **kw: SimpleNamespace(**kw),
            'depset': lambda value: value,
        }
        tree = ast.parse((ROOT / 'msbuild/private/sdk_bootstrap.bzl').read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_runtime')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'sdk_bootstrap.bzl', 'exec'), namespace)
        for newline in ['\n', '\r\n']:
            with self.subTest(newline=repr(newline)), tempfile.TemporaryDirectory(prefix='sdk-copy-') as temporary:
                folder = Path(temporary)
                dotnet = SimpleNamespace(path='SDK with spaces/dotnet.exe', dirname='SDK with spaces', basename='dotnet.exe')
                extra = SimpleNamespace(path='SDK with spaces/sdk/11.0.100/space directory/reference file.dll')
                for file in [dotnet, extra]:
                    path = folder / file.path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(file.path)
                values, captured = [], {}
                options = {}
                arguments = SimpleNamespace(
                    add=lambda value: values.append(value), add_all=lambda value: values.extend(value),
                    set_param_file_format=lambda value: options.update(format=value),
                    use_param_file=lambda value, **kw: options.update(template=value, **kw))
                ctx = SimpleNamespace(
                    label=SimpleNamespace(name='host'), executable=SimpleNamespace(dotnet=dotnet),
                    files=SimpleNamespace(files=[dotnet, extra]),
                    attr=SimpleNamespace(runtime_only=False, runtime_identifier='win-x64', version='11.0.0'),
                    actions=SimpleNamespace(declare_directory=lambda name: SimpleNamespace(path=name),
                                            args=lambda: arguments, run_shell=lambda **kw: captured.update(kw)))
                providers = namespace['_runtime'](ctx)
                self.assertEqual(providers[1].entry_point, 'dotnet.exe')
                self.assertEqual(options, {'format': 'multiline', 'template': '%s', 'use_always': True})
                params = folder / 'copy response file.params'
                params.write_bytes((newline.join(value if isinstance(value, str) else value.path for value in values) + newline).encode())
                subprocess.run(['bash', '-c', captured['command'], '--', str(params)], cwd=folder,
                               check=True, capture_output=True, text=True, timeout=30)
                for file in [dotnet, extra]:
                    relative = file.path[len(dotnet.dirname) + 1:]
                    self.assertEqual((folder / 'host.runtime' / relative).read_text(), file.path)


if __name__ == '__main__':
    unittest.main()
