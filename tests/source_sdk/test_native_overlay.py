"""Portable checks for the source SDK native overlay's fail-closed gates."""
import hashlib
import importlib.util
import io
import subprocess
from contextlib import redirect_stderr
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('native_overlay')/'install.py'
spec = importlib.util.spec_from_file_location('native_overlay_install', SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class NativeOverlayTests(unittest.TestCase):
    def test_base_requires_immutable_ubuntu_arm64_llvm18(self):
        reference = 'local/base@sha256:' + 'a'*64
        release = {'ID': 'ubuntu', 'VERSION_ID': '26.04'}
        installer.validate_base(reference, release, 'arm64', 'Ubuntu clang version 18.1.8')
        for args in [('local/base:latest', release, 'arm64', 'clang version 18.1.8'),
                     (reference, release, 'amd64', 'clang version 18.1.8'),
                     (reference, release, 'arm64', 'clang version 21.0.0')]:
            with self.assertRaises(ValueError):
                installer.validate_base(*args)

    def test_archive_bytes_and_identity_must_both_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)/'package.deb'
            archive.write_bytes(b'archive fixture')
            package = dict(name='file', version='1:5.46-5build2', architecture='arm64',
                           sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
            installer.validate_archive(archive, package, lambda _: ('file', '1:5.46-5build2', 'arm64'))
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                installer.validate_archive(archive, package, lambda _: ('file', 'wrong', 'arm64'))
            archive.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                installer.validate_archive(archive, package, lambda _: ('file', '1:5.46-5build2', 'arm64'))

    def test_offline_cache_contains_only_verified_archives_and_exact_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root/'cache'; cache.mkdir()
            archive = root/'file_1%3a5.46-5build2_arm64.deb'
            archive.write_bytes(b'verified')
            package = dict(name='file', version='1:5.46-5build2', architecture='arm64',
                           sha256=hashlib.sha256(b'verified').hexdigest())
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                installer.stage_verified_archive(archive, package, lambda _: ('file', 'wrong', 'arm64'), cache)
            self.assertEqual(list(cache.iterdir()), [])
            cached = installer.stage_verified_archive(archive, package, lambda _: ('file', '1:5.46-5build2', 'arm64'), cache)
            self.assertEqual(cached.read_bytes(), b'verified')
            command = installer.offline_command(cache, [package])
            self.assertIn('--no-download', command)
            self.assertIn('Dir::Cache::archives='+str(cache), command)
            self.assertEqual(command[-1], 'file=1:5.46-5build2')
            self.assertNotIn(str(archive), command)

    def test_transaction_rejects_unlisted_installs_and_removals(self):
        allowed = {'file', 'libmagic1t64'}
        installer.validate_transaction('Inst file (1:5.46-5build2 Ubuntu:26.04)\nInst libmagic1t64:arm64 (1 Ubuntu:26.04)\n', allowed)
        with self.assertRaisesRegex(ValueError, 'unlisted package'):
            installer.validate_transaction('Inst unexpected (1 Ubuntu:26.04)\n', allowed)
        with self.assertRaisesRegex(ValueError, 'would remove'):
            installer.validate_transaction('  Remv curl [1]\n', allowed)

    def test_simulation_failure_preserves_apt_diagnostic(self):
        failure = subprocess.CalledProcessError(100, ['apt-get'], output='missing archive detail\n')
        output = io.StringIO()
        with patch.object(installer.subprocess, 'check_output', side_effect=failure), redirect_stderr(output):
            with self.assertRaises(subprocess.CalledProcessError):
                installer.simulate_transaction(['apt-get', 'install'], {}, set())
        self.assertEqual(output.getvalue(), 'missing archive detail\n')

    def test_recorded_overlay_has_exact_unique_packages(self):
        manifest = json.loads(installer.MANIFEST.read_text())
        packages = manifest['packages']
        self.assertEqual(len(packages), 17)
        self.assertEqual(len({row['name'] for row in packages}), 17)
        versions = {row['name']: row['version'] for row in packages}
        self.assertEqual(versions['lldb-18'], '1:18.1.8-20ubuntu8')
        self.assertEqual(versions['liblldb-18-dev'], '1:18.1.8-20ubuntu8')
        self.assertIn('file', versions)
        self.assertIn('libbrotli-dev', versions)


if __name__ == '__main__':
    unittest.main()
