"""Portable controls for recovery boundaries; no source producer runs."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import source_action_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def exercise(self, root, sdk, explicit_stop=False, smoke=False, reported_digest=None, test_executed=True):
        seed = root / 'seed'
        seed.mkdir()
        (seed / 'app-contract.json').write_text(json.dumps({'SdkVersion': sdk}))
        (seed / 'App.cs').write_text('original')
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
                if smoke:
                    rows[0]['actualOutputs'] = [dict(path='out/sdk.generated/sdk.tar.gz',
                                                     digest={'hash': reported_digest or recovery.digest(archive)})]
                    rows.append(dict(mnemonic='TestRunner', cacheHit=not test_executed,
                                     commandArgs=['/fixture/test-setup.sh']))
                    print('SDK_FROM_SOURCE=' + sdk.split('.')[0] + '.0.0', file=kwargs['stdout'])
                if log.stem != 'recover.execution':
                    rows += [dict(mnemonic='MSBuildGraph', cacheHit=False),
                             dict(mnemonic='TestRunner', cacheHit=False, commandArgs=['/fixture/test-setup.sh'])]
                log.write_text(''.join(json.dumps(row) for row in rows))
                recovered = folder / 'workspace/bazel-out/oracle/sdk.generated/sdk.tar.gz'
                if not smoke:
                    recovered.parent.mkdir(parents=True, exist_ok=True)
                    recovered.write_bytes(b'produced SDK')
            return type('Completed', (), {'returncode': 0})()

        args = ['recovery', str(seed), str(folder), '--cache=https://fixture.invalid']
        if smoke:
            args += ['--smoke-only', '--remote-connections=1']
        if explicit_stop:
            args += ['--seed-output-base=' + str(base)]
        with patch('sys.argv', args), patch.dict(os.environ, RULES_MSBUILD_BAZEL='/fixture/bazel'), \
                patch.object(recovery.subprocess, 'run', side_effect=run):
            recovery.main()
        self.assertEqual((seed / 'App.cs').read_text(), 'original')
        if not smoke:
            self.assertIn('"' + sdk.split('.')[0] + '.0.0"', (folder / 'workspace/App.cs').read_text())
        self.assertTrue(all('--nocache_test_results' in command for command in calls[-2:]))
        return calls, json.loads((folder / 'report.json').read_text())

    def test_smoke_recovers_without_materializing_sdk(self):
        with tempfile.TemporaryDirectory() as temporary:
            calls, report = self.exercise(Path(temporary), '11.0.100', smoke=True)
            self.assertEqual(len(calls), 1)
            self.assertIn('--nocache_test_results', calls[0])
            self.assertIn('--remote_download_outputs=toplevel', calls[0])
            self.assertIn('--remote_max_connections=1', calls[0])
            self.assertEqual(report['downloadOutputs'], 'toplevel')

    def test_smoke_rejects_wrong_sdk_or_cached_test(self):
        for overrides in [{'reported_digest': 'wrong'}, {'test_executed': False}]:
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
