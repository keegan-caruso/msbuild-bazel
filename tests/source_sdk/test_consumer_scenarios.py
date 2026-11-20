"""Exercise consumer startup flags and source-reuse evidence rejection."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConsumerScenarioTests(unittest.TestCase):
    def run_fixture(self, root, producer_miss=False, sdk_version='10.0.100', wrong_host=False):
        workspace = root / 'workspace'
        workspace.mkdir()
        (workspace / 'BUILD.bazel').write_text('')
        (workspace / 'app-contract.json').write_text(json.dumps({'SdkVersion': sdk_version}))
        bazel = root / 'bazel'
        bazel.write_text('''#!/usr/bin/env python3
import json, os, sys, zipfile
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['FIXTURE_COMMANDS'], 'a') as log: log.write(json.dumps(args)+'\\n')
if 'shutdown' in args: raise SystemExit(0)
execution = next(a.split('=',1)[1] for a in args if a.startswith('--execution_log_json_file='))
rows = []
if os.environ.get('FIXTURE_SOURCE_MISS') == '1':
    rows.append(dict(mnemonic='SourceSdkBuild', cacheHit=False))
Path(execution).write_text(''.join(json.dumps(row) for row in rows))
if '//scenarios:package_test' in args:
    print('SOURCE_SDK_PACKAGE=42')
elif '//scenarios:razor_test' in args:
    print('<p>source SDK razor</p>')
else:
    package = Path('bazel-bin/scenarios/pack/SourceSdk.Package.1.0.0.nupkg')
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('package.nuspec', '<package><metadata><id>SourceSdk.Package</id><version>1.0.0</version></metadata></package>')
        archive.writestr('lib/' + os.environ['FIXTURE_TFM'] + '/Package.dll', b'MZfixture')
    runtime = Path('bazel-bin/produced_runtime.runtime/dotnet')
    runtime.parent.mkdir(parents=True)
    core = runtime.parent / 'shared/Microsoft.NETCore.App' / os.environ['FIXTURE_RUNTIME'] / 'System.Private.CoreLib.dll'
    core.parent.mkdir(parents=True)
    core.write_bytes(b'fixture')
    identity = dict(runtimeVersion=os.environ['FIXTURE_RUNTIME'], processPath=str(runtime.resolve()) if os.environ['FIXTURE_WRONG_HOST'] == '0' else '/bin/sh', coreLibraryPath=str(core.resolve()))
    runtime.write_text('#!/bin/sh\\necho SOURCE_SDK_PUBLISH\\necho ' + repr(json.dumps(identity)) + '\\n')
    runtime.chmod(0o755)
''')
        bazel.chmod(0o755)
        commands = root / 'commands.jsonl'
        environment = dict(os.environ, RULES_MSBUILD_BAZEL=str(bazel),
                           FIXTURE_COMMANDS=str(commands), FIXTURE_SOURCE_MISS='1' if producer_miss else '0',
                           FIXTURE_TFM='net' + '.'.join(sdk_version.split('.')[:2]),
                           FIXTURE_RUNTIME='.'.join(sdk_version.split('.')[:2]) + '.0',
                           FIXTURE_WRONG_HOST='1' if wrong_host else '0')
        command = [sys.executable, str(Path(__file__).with_name('consumer_scenarios.py')),
                   str(root / 'reports'), '--workspace=' + str(workspace),
                   '--output-base=' + str(root / 'base'), '--batch',
                   '--bazel-startup-option=--host_jvm_args=-Xmx1024m',
                   '--bazel-startup-option=--output_user_root=' + str(root / 'user'),
                   '--require-source-reuse']
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
        return result, [json.loads(line) for line in commands.read_text().splitlines()]

    def test_startup_options_reach_every_consumer_and_shutdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, commands = self.run_fixture(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(commands), 4)
            for command in commands:
                self.assertEqual(command[:2], ['--host_jvm_args=-Xmx1024m', '--output_user_root=' + str(root / 'user')])
                self.assertIn('--output_base=' + str((root / 'base').resolve()), command)
            cases = json.loads((root / 'reports/scenarios-report.json').read_text())
            self.assertEqual(cases[-1]['output'], 'SOURCE_SDK_PUBLISH')

    def test_net11_contract_and_source_host_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result, commands = self.run_fixture(root, sdk_version='11.0.100')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('net11.0', (root / 'workspace/scenarios/Publish.csproj').read_text())
            self.assertNotIn('net10.0', (root / 'workspace/scenarios/BUILD.bazel').read_text())
            self.assertIn('--nocache_test_results', commands[0])

    def test_rejects_runtime_from_another_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, _ = self.run_fixture(Path(temporary), wrong_host=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('processPath', result.stderr)

    def test_source_rebuild_evidence_stops_remaining_consumers(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, commands = self.run_fixture(Path(temporary), producer_miss=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('SourceSdkBuild', result.stderr)
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[-1][-1], 'shutdown')


if __name__ == '__main__':
    unittest.main()
