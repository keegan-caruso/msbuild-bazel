"""Portable controls for recovery boundaries; no source producer runs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import source_action_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def exercise(self, root, sdk, explicit_stop=False, smoke=False, reported_digest=None, test_executed=True, graph_observed=True, profile=False, launcher=None, seed_direct=False):
        seed = root / 'seed'
        seed.mkdir()
        (seed / 'app-contract.json').write_text(json.dumps({'SdkVersion': sdk}))
        (seed / 'App.cs').write_text('original')
        declaration = 'msbuild_graph_test(name="smoke",graph=":graph",project="App.csproj"'
        declaration += ',direct_executable_smoke=True)' if seed_direct else ')'
        (seed / 'BUILD.bazel').write_text(declaration)
        base = root / 'producer-base'
        output = base / 'execroot/main/bazel-out' if explicit_stop else seed / 'bazel-out'
        output.mkdir(parents=True)
        if explicit_stop:
            (seed / 'bazel-out').symlink_to(output)
        archive = output / 'oracle/sdk.generated/sdk.tar.gz'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b'produced SDK')
        folder = root / 'recovery'
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if 'shutdown' not in command:
                log = Path(next(c.split('=', 1)[1] for c in command if c.startswith('--execution_log_json_file=')))
                rows = [dict(mnemonic='SourceSdkBuild', cacheHit=True)]
                if graph_observed:
                    rows.append(dict(mnemonic='MSBuildGraph', cacheHit=True))
                if smoke:
                    rows[0]['actualOutputs'] = [dict(path='out/sdk.generated/sdk.tar.gz',
                                                     digest={'hash': reported_digest or recovery.digest(archive)})]
                    rows.append(dict(mnemonic='TestRunner', cacheHit=not test_executed,
                                     commandArgs=['/fixture/test-setup.sh'], metrics={'executionWallTime': '0.076s'},
                                     inputs=[{'path': 'bazel-out/bin/smoke.runfiles/_main/runtime/shared/Microsoft.NETCore.App/11.0.0/CoreLib.dll',
                                              'digest': {'sizeBytes': '42', 'hash': 'abc'}}]))
                    print('SDK_FROM_SOURCE=' + sdk.split('.')[0] + '.0.0', file=kwargs['stdout'])
                if log.stem != 'recover.execution':
                    rows += [dict(mnemonic='MSBuildGraph', cacheHit=False),
                             dict(mnemonic='TestRunner', cacheHit=False, commandArgs=['/fixture/test-setup.sh'])]
                log.write_text(''.join(json.dumps(row) for row in rows))
                if profile:
                    trace = Path(next(c.split('=', 1)[1] for c in command if c.startswith('--profile=')))
                    trace.write_text(json.dumps({'traceEvents': []}))
                recovered = folder / 'workspace/bazel-out/oracle/sdk.generated/sdk.tar.gz'
                if not smoke:
                    recovered.parent.mkdir(parents=True, exist_ok=True)
                    recovered.write_bytes(b'produced SDK')
            return type('Completed', (), {'returncode': 0})()

        args = ['recovery', str(seed), str(folder), '--cache=https://fixture.invalid']
        if profile:
            args += ['--profile']
        if launcher:
            args += ['--smoke-launcher=' + launcher]
        if smoke:
            args += ['--smoke-only', '--remote-connections=1']
        if explicit_stop:
            args += ['--seed-output-base=' + str(base)]
        with patch('sys.argv', args), patch.dict(os.environ, RULES_MSBUILD_BAZEL='/fixture/bazel'), \
                patch.object(recovery.subprocess, 'run', side_effect=run):
            recovery.main()
        self.assertEqual((seed / 'App.cs').read_text(), 'original')
        self.assertEqual((seed / 'BUILD.bazel').read_text(), declaration)
        if not smoke:
            self.assertIn('"' + sdk.split('.')[0] + '.0.0"', (folder / 'workspace/App.cs').read_text())
        self.assertTrue(all('--nocache_test_results' in command for command in calls[-2:]))
        return calls, json.loads((folder / 'report.json').read_text())

    def test_launcher_override_preserves_console_runtime_for_both_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = root / 'BUILD.bazel'
            classic = 'msbuild_graph_test(name="smoke",graph=":graph",project="App.csproj",runtime_host=":console_runtime")'
            build.write_text(classic)
            self.assertEqual(recovery.configure_launcher(root, 'direct'), 'direct')
            self.assertIn('runtime_host=":console_runtime",direct_executable_smoke=True', build.read_text())
            self.assertEqual(recovery.configure_launcher(root, 'classic'), 'classic')
            self.assertEqual(build.read_text(), classic)

    def test_launcher_override_requires_smoke_only(self):
        for mode in ['classic', 'direct']:
            with self.subTest(mode=mode), patch('sys.argv', ['recovery', 'seed', 'trial', '--cache=https://fixture.invalid',
                                                          '--smoke-launcher=' + mode]), \
                    patch('sys.stderr'):
                with self.assertRaises(SystemExit) as error:
                    recovery.main()
                self.assertEqual(error.exception.code, 2)

    def test_full_profile_keeps_cached_test_oracle(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, report = self.exercise(Path(temporary), '11.0.100', profile=True)
            self.assertEqual(len(report['runs']), 3)
            self.assertFalse(report['runs'][0]['runfiles']['available'])
            self.assertIsNone(report['runs'][0]['testExecutionSeconds'])

    def test_launcher_overrides_only_trial_and_preserves_seed_default(self):
        for seed_direct, launcher in [(True, None), (True, 'classic'), (False, 'direct')]:
            with self.subTest(seed_direct=seed_direct, launcher=launcher), tempfile.TemporaryDirectory() as temporary:
                _, report = self.exercise(Path(temporary), '11.0.100', smoke=True,
                                          seed_direct=seed_direct, launcher=launcher)
                self.assertEqual(report['smokeLauncher'], launcher or 'direct')

    def test_launcher_rejects_unknown_or_duplicate_declaration(self):
        declaration = 'msbuild_graph_test(name="smoke",graph=":graph",project="App.csproj")'
        for text in ['unknown', declaration + '\n' + declaration, 'wrapper(' + declaration + ')',
                     declaration.replace('App.csproj', 'AppXcsproj')]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'BUILD.bazel').write_text(text)
                with self.assertRaises(ValueError):
                    recovery.configure_launcher(root, 'direct')

    def test_profile_flag_and_execution_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls, report = self.exercise(Path(temporary), '11.0.100', smoke=True, profile=True, launcher='direct')
            self.assertTrue(report['profile'])
            self.assertIn('--generate_json_trace_profile', calls[0])
            self.assertIn('--noslim_profile', calls[0])
            self.assertIn('--experimental_profile_include_target_label', calls[0])
            run = report['runs'][0]
            self.assertEqual(run['testExecutionSeconds'], .076)
            self.assertTrue(Path(run['profile']['path']).is_file())
            self.assertTrue(Path(run['runfiles']['path']).is_file())
            self.assertEqual(run['runfiles']['logicalBytes'], 42)

    def test_profile_scopes_staging_to_enclosing_smoke_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'profile.json'
            path.write_text(json.dumps({'traceEvents': [
                {'name': 'stage remote inputs', 'cat': 'remote output download', 'ph': 'X', 'dur': 2_000_000, 'tid': 1, 'ts': 100},
                {'name': 'stage remote inputs', 'cat': 'remote output download', 'ph': 'X', 'dur': 3_000_000, 'tid': 2, 'ts': 100},
                {'name': 'stage remote inputs', 'cat': 'other', 'ph': 'X', 'dur': 100_000_000},
                {'name': 'Testing //:smoke', 'cat': 'action processing', 'ph': 'X', 'dur': 4_000_000, 'tid': 1, 'ts': 0,
                 'args': {'mnemonic': 'TestRunner', 'target': '//:smoke'}}]}))
            summary = recovery.profile_summary(path)
            self.assertEqual(summary['remoteInputStagingSpanSeconds'], 5)
            self.assertEqual(summary['testRemoteInputStagingSpanSeconds'], 2)
            path.write_text('{"traceEvents": []}')
            self.assertIsNone(recovery.profile_summary(path)['remoteInputStagingSpanSeconds'])
            self.assertIsNone(recovery.profile_summary(path)['testRemoteInputStagingSpanSeconds'])

    def test_log_inventory_excludes_other_runfiles_and_counts_logical_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = [{'path': 'bin/smoke.runfiles/_main/' + runtime + '/shared/Microsoft.NETCore.App/11.0.0/CoreLib.dll',
                        'digest': {'sizeBytes': '42', 'hash': 'abc'}} for runtime in ['selected', 'helper']]
            entries.append({'path': 'bin/other.runfiles/ignored', 'digest': {'sizeBytes': '100'}})
            result = recovery.runfiles_inventory([{'mnemonic': 'TestRunner', 'commandArgs': ['/fixture/test-setup.sh'], 'runfilesInputs': entries},
                                                  {'mnemonic': 'TestRunner', 'commandArgs': ['/fixture/xml.sh'], 'runfilesInputs': entries}], root / 'inventory.json')
            self.assertEqual(result['source'], 'execution-log')
            self.assertEqual(result['logicalBytes'], 84)
            self.assertEqual(result['fileCount'], 2)
            self.assertEqual(len(result['frameworkLayouts']), 2)
            self.assertFalse(recovery.runfiles_inventory([], root / 'empty.json')['available'])

    def test_action_reader_preserves_default_summary_and_limits_details_to_test_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'execution.json'
            rows = [dict(mnemonic='TestRunner', commandArgs=[command], metrics={'executionWallTime': '0.076s'},
                         inputs=[{'path': 'bin/smoke.runfiles/core'}])
                    for command in ['/fixture/test-setup.sh', '/fixture/xml.sh']]
            path.write_text(''.join(json.dumps(row) for row in rows))
            self.assertTrue(all('metrics' not in row and 'runfilesInputs' not in row for row in recovery.actions(path)))
            details = recovery.actions(path, include_test_details=True)
            self.assertIn('metrics', details[0])
            self.assertNotIn('metrics', details[1])
            self.assertNotIn('runfilesInputs', details[1])

    def test_execution_duration_excludes_cached_or_xml_generation_spawns(self):
        rows = [{'mnemonic': 'TestRunner', 'cacheHit': False, 'commandArgs': ['/fixture/test-setup.sh'],
                 'metrics': {'executionWallTime': '0.076s'}},
                {'mnemonic': 'TestRunner', 'cacheHit': False, 'commandArgs': ['/fixture/xml.sh'],
                 'metrics': {'executionWallTime': '10s'}},
                {'mnemonic': 'TestRunner', 'cacheHit': True, 'commandArgs': ['/fixture/test-setup.sh'],
                 'metrics': {'executionWallTime': '10s'}}]
        self.assertEqual(recovery.test_execution_seconds(rows), .076)
        rows[0]['metrics'] = {}
        self.assertIsNone(recovery.test_execution_seconds(rows))

    def test_smoke_recovers_without_materializing_sdk(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls, report = self.exercise(Path(temporary), '11.0.100', smoke=True)
            self.assertEqual(len(calls), 1)
            self.assertIn('--nocache_test_results', calls[0])
            self.assertIn('--remote_download_outputs=toplevel', calls[0])
            self.assertIn('--remote_max_connections=1', calls[0])
            self.assertEqual(report['downloadOutputs'], 'toplevel')

    def test_smoke_rejects_wrong_sdk_or_cached_test(self):
        for overrides in [{'reported_digest': 'wrong'}, {'test_executed': False}, {'graph_observed': False}]:
            with self.subTest(overrides=overrides), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(AssertionError):
                    self.exercise(Path(temporary), '11.0.100', smoke=True, **overrides)

    def test_external_stopped_producer_with_synthetic_oracle_stays_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls, report = self.exercise(Path(temporary), '10.0.100')
            self.assertEqual(len(calls), 3)
            self.assertIsNone(report['stoppedProducerOutputBase'])

    def test_net11_explicit_shutdown_precedes_fresh_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls, report = self.exercise(Path(temporary), '11.0.100', explicit_stop=True)
            self.assertIn('shutdown', calls[0])
            self.assertEqual(report['runtimeVersion'], '11.0.0')
            self.assertEqual(len(report['runs']), 3)


if __name__ == '__main__':
    unittest.main()
