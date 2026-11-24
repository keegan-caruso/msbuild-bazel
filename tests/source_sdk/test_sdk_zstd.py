"""Full SDK recompression preserves the exact tar stream and its extraction."""
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest

from sdk_zstd import recompress
from source_action_prepare import write_bazel_files
from test_sdk_pack_layout import layout

try:
    from compression import zstd
except ImportError:
    zstd = None


class SdkZstdTests(unittest.TestCase):
    def test_optional_targets_are_reachable_and_leave_legacy_targets_intact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_bazel_files(root, root, zstd=True)
            tree = ast.parse((root / 'BUILD.bazel').read_text())
            rules = {next(kw.value.value for kw in node.value.keywords if kw.arg == 'name'): node.value
                     for node in tree.body if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Call) and node.value.func.id != 'load'}
            self.assertEqual(rules['sdk_zstd'].func.id, 'sdk_zstd')
            self.assertEqual(next(kw.value.value for kw in rules['layout_zstd'].keywords if kw.arg == 'archive'), ':sdk_zstd')
            self.assertEqual(next(kw.value.value for kw in rules['layout'].keywords if kw.arg == 'archive'), ':sdk')
            self.assertTrue((root / 'sdk_zstd.py').is_file())

    @unittest.skipUnless(zstd and sys.version_info[:2] == (3, 14), 'requires Python 3.14 compression.zstd')
    def test_lossless_deterministic_checksum_and_actual_layout_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name, data, mode in [('dotnet', b'host\0', 0o755), ('sdk/11.0.100/compiler.dll', b'compiler', 0o644), ('packs/Ref/ref.dll', b'reference', 0o644)]:
                    entry = tarfile.TarInfo(name)
                    entry.size, entry.mode, entry.mtime = len(data), mode, 1234567890
                    archive.addfile(entry, io.BytesIO(data))
                link = tarfile.TarInfo('sdk/link')
                link.type, link.linkname = tarfile.SYMTYPE, '11.0.100/compiler.dll'
                archive.addfile(link)
            original = root / 'sdk.tar.gz'
            original.write_bytes(gzip.compress(raw.getvalue(), mtime=11))
            compressed, provenance = root / 'sdk.tar.zst', root / 'provenance.json'
            recompress(original, compressed, provenance)
            first = compressed.read_bytes()
            recompress(original, compressed, provenance)
            self.assertEqual(first, compressed.read_bytes())
            with zstd.open(compressed) as stream:
                self.assertEqual(stream.read(), raw.getvalue())
            report = json.loads(provenance.read_text())
            self.assertEqual(report['upstreamGzipSha256'], hashlib.sha256(original.read_bytes()).hexdigest())
            self.assertEqual(report['tarSha256'], hashlib.sha256(raw.getvalue()).hexdigest())
            self.assertEqual(report['zstdSha256'], hashlib.sha256(first).hexdigest())
            self.assertEqual(report['compression']['checksum_flag'], 1)
            _, action = layout(root, [], [])
            action['arguments'][0] = str(compressed)
            subprocess.run(['bash', '-c', action['command'].replace('python3 ', shlex.quote(sys.executable) + ' '), 'layout', *action['arguments']], check=True)
            self.assertEqual((root / 'layout/dotnet').read_bytes(), b'host\0')
            self.assertEqual((root / 'layout/dotnet').stat().st_mode & 0o777, 0o755)
            self.assertTrue((root / 'layout/sdk/link').is_symlink())
            self.assertEqual((root / 'layout/sdk/link').read_bytes(), b'compiler')
            corrupt = bytearray(first)
            corrupt[-1] ^= 1
            compressed.write_bytes(corrupt)
            with self.assertRaises(zstd.ZstdError):
                with zstd.open(compressed) as stream:
                    stream.read()


if __name__ == '__main__':
    unittest.main()
