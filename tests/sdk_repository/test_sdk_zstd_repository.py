"""Bazel's public SDK archive API verifies and extracts zstd, including suffixless URLs."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

try:
    from compression import zstd
except ImportError:
    zstd = None

ROOT = Path(__file__).resolve().parents[2]
BAZEL = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT / 'scripts/bazel-launcher.sh'))


@unittest.skipUnless(zstd, 'requires Python 3.14 compression.zstd')
class SdkZstdRepositoryTests(unittest.TestCase):
    def query(self, mismatch=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                for name in ['dotnet', 'sdk/11.0.100/version.txt', 'shared/Microsoft.NETCore.App/11.0.0/version.txt']:
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode = 3, 0o755
                    archive.addfile(entry, io.BytesIO(b'sdk'))
            source = root / 'payload'
            source.write_bytes(zstd.compress(stream.getvalue()))
            integrity = 'sha256-' + base64.b64encode(bytes(32) if mismatch else hashlib.sha256(source.read_bytes()).digest()).decode()
            (root / 'MODULE.bazel').write_text(
                'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
                'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
                'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
                'dotnet.sdk_archive(name="sdk",version="11.0.100",runtime_version="11.0.0",platform="linux-arm64",'
                'urls=[' + json.dumps(source.as_uri()) + '],integrity=' + json.dumps(integrity) + ',type="tar.zst")\n'
                'use_repo(dotnet,"sdk")\n')
            (root / 'BUILD.bazel').write_text('')
            result = subprocess.run([BAZEL, '--batch', '--output_base=' + str(root / 'base'), '--ignore_all_rc_files',
                                     'query', 'deps(@sdk//:files)', '--lockfile_mode=off'], cwd=root, capture_output=True, text=True, timeout=120)
            output = result.stdout + result.stderr
            if mismatch:
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn('Checksum', output)
            else:
                self.assertEqual(result.returncode, 0, output)
                self.assertIn('sdk/dotnet', output)
                self.assertIn('sdk/sdk/11.0.100/version.txt', output)

    def test_public_zstd_sdk_with_suffixless_url(self):
        self.query()

    def test_zstd_sdk_rejects_wrong_digest(self):
        self.query(mismatch=True)


if __name__ == '__main__':
    unittest.main()
