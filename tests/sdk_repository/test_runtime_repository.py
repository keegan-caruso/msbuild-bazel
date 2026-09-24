"""Runtime archive integrity and extension validation through actual Bazel."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
BAZEL = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT/'scripts/bazel-launcher.sh'))


class RuntimeRepository(unittest.TestCase):
    def query(self, declaration, error=None, integrity=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archive=root/'runtime.tar.gz'
            with tarfile.open(archive,'w:gz') as out:
                data=b'#!/bin/sh\nexit 0\n'
                item=tarfile.TarInfo('dotnet');item.size=len(data);item.mode=0o755
                out.addfile(item,io.BytesIO(data))
            digest='sha256-'+base64.b64encode(hashlib.sha256(archive.read_bytes()).digest()).decode()
            declaration=declaration.replace('ARCHIVE',json.dumps(archive.as_uri())).replace('INTEGRITY',json.dumps(integrity or digest))
            (root/'MODULE.bazel').write_text('bazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'+declaration+'\nuse_repo(dotnet,"runtime")\n')
            (root/'BUILD.bazel').write_text('')
            result=subprocess.run([BAZEL,'--batch','--output_base='+str(root/'base'),'--ignore_all_rc_files','query','@runtime//:runtime','--lockfile_mode=off'],cwd=root,text=True,capture_output=True,timeout=120)
            output=result.stdout+result.stderr
            if error:
                self.assertNotEqual(result.returncode,0,output)
                self.assertIn(error,output)
            else:self.assertEqual(result.returncode,0,output)

    def test_custom_verified_archive(self):
        self.query('dotnet.runtime_archive(name="runtime",version="custom",platform="linux-arm64",urls=[ARCHIVE],integrity=INTEGRITY)')

    def test_checksum_mismatch(self):
        self.query('dotnet.runtime_archive(name="runtime",version="custom",platform="linux-arm64",urls=[ARCHIVE],integrity=INTEGRITY)', 'Checksum', 'sha256-'+base64.b64encode(bytes(32)).decode())

    def test_unknown_version(self):
        self.query('dotnet.runtime(name="runtime",version="unknown")','Unknown runtime version')

    def test_unknown_platform(self):
        self.query('dotnet.runtime(name="runtime",version="10.0.0",platforms=["unknown"])','Unsupported runtime platform')

    def test_missing_integrity(self):
        self.query('dotnet.runtime_archive(name="runtime",version="custom",platform="linux-arm64",urls=[ARCHIVE],integrity="")','Runtime archives require integrity')
