"""Portable controls for the source-runtime trial harness."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT/'tests/graph_build/upstream/runtime_source_trials.py'
spec = importlib.util.spec_from_file_location('runtime_source_trials', SCRIPT)
trials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trials)


class RuntimeSourceTrialTests(unittest.TestCase):
    def test_replacement_breaks_hardlink_and_restores_mode_and_timestamps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, linked = root/'source.cs', root/'retained.cs'
            source.write_bytes(b'original')
            source.chmod(0o751)
            os.utime(source, ns=(1_600_000_000_000_000_000, 1_600_000_001_000_000_000))
            os.link(source, linked)
            original = source.stat()
            trials.replace_input(source, b'edited')
            self.assertNotEqual(source.stat().st_ino, linked.stat().st_ino)
            self.assertEqual(linked.read_bytes(), b'original')
            self.assertEqual(source.read_bytes(), b'edited')
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o751)
            trials.replace_input(source, b'original', original)
            restored = source.stat()
            self.assertEqual(stat.S_IMODE(restored.st_mode), 0o751)
            self.assertEqual((restored.st_atime_ns, restored.st_mtime_ns),
                             (original.st_atime_ns, original.st_mtime_ns))
            self.assertEqual(source.read_bytes(), b'original')
            self.assertEqual(linked.read_bytes(), b'original')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['retained.cs', 'source.cs'])

    def test_brokers_find_renamed_java_for_owned_base_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proc = root/'proc'
            proc.mkdir()
            base = root/'owned-base'
            base.mkdir()
            other = root/'owned-base-other'
            other.mkdir()
            java = root/'java'
            java.touch()
            dotnet = root/'dotnet'
            dotnet.touch()

            def process(pid, parent, executable, cwd, args):
                folder = proc/str(pid)
                folder.mkdir()
                (folder/'exe').symlink_to(executable)
                (folder/'cwd').symlink_to(cwd)
                (folder/'status').write_text('Name:\tfixture\nPPid:\t' + str(parent) + '\n')
                (folder/'cmdline').write_bytes(b'\0'.join(os.fsencode(x) for x in args) + b'\0')

            process(20, 1, java, root, ['bazel(workspace)', '--output_base='+str(base)])
            process(21, 20, dotnet, base, ['dotnet', 'worker', '/tool/graph_runner.runner/GraphBuild.dll'])
            process(22, 1, java, root, ['bazel(other)', '--output_base='+str(other)])
            process(23, 22, dotnet, other, ['dotnet', 'worker', '/tool/graph_runner.runner/GraphBuild.dll'])
            process(24, 1, dotnet, base, ['dotnet', 'worker', '/tool/graph_runner.runner/GraphBuild.dll'])
            process(25, 20, dotnet, base, ['dotnet', 'worker', '/tool/driver_runner.runner/GraphBuild.dll'])
            self.assertEqual(trials.brokers(base, proc), [21])

    def test_runtime_proof_reads_zip_and_direct_outputs(self):
        proof = {'managed': 2, 'native': 1, 'sdkAbsentExecution': True, 'packageVerified': True}
        files = {'runtime.json': json.dumps(proof), 'runtime.launcher.log': 'launcher',
                 'runtime.sdk-absent.log': 'sdk absent', 'runtime.package-sdk-absent.log': 'package absent'}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root/'outputs.zip'
            with zipfile.ZipFile(archive, 'w') as zipped:
                for name, data in files.items():
                    zipped.writestr('test.outputs/' + name, data)
            direct_dir = root/'test.outputs'
            direct_dir.mkdir()
            for name, data in files.items():
                (direct_dir/name).write_text(data)
            for outputs in ([{'name': 'test.outputs/outputs.zip', 'uri': archive.as_uri()}],
                            [{'name': 'test.outputs/' + name, 'uri': (direct_dir/name).as_uri()}
                             for name in files]):
                records = [{'id': {'testResult': {'label': '//:runtime_test'}},
                            'testResult': {'testActionOutput': outputs}}]
                actual, logs = trials.runtime_proof(records, root/'result.json')
                self.assertEqual(actual, proof)
                self.assertEqual(set(logs), set(files) - {'runtime.json'})
                self.assertEqual(json.loads((root/'result.json').read_text()), proof)
            # Ambiguous entries and a path masquerading as a different file fail closed.
            direct = [{'name': 'test.outputs/' + name, 'uri': (direct_dir/name).as_uri()} for name in files]
            for invalid in (direct + [direct[0]], direct + [{'name': 'outputs.zip', 'uri': archive.as_uri()}],
                            [dict(direct[0], uri=(direct_dir/'runtime.launcher.log').as_uri())] + direct[1:]):
                records = [{'id': {'testResult': {'label': '//:runtime_test'}},
                            'testResult': {'testActionOutput': invalid}}]
                with self.assertRaises(AssertionError):
                    trials.runtime_proof(records, root/'invalid.json')

    def test_cli_help_exposes_oracle_and_mappings(self):
        output = subprocess.check_output([sys.executable, str(SCRIPT), '--help'], text=True)
        self.assertIn('--oracle', output)
        self.assertIn('--qualification-mappings', output)
        self.assertIn('--expected-mappings-sha256', output)


if __name__ == '__main__':
    unittest.main()
