"""Exercise shell bootstrap decisions with tiny tools, without Python in child PATH.

This does not qualify Microsoft's Linux SDK on macOS. It verifies download hashes,
installation and repeat-run behavior around the real shell bootstrap.
"""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'.bazelversion').write_text('9.2.0\n')
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('setup.sh', 'env.sh', 'tooling.sh', 'dotnet.sh', 'check.sh', 'bazel-launcher.sh'):
            shutil.copy(ROOT / 'scripts' / name, scripts / name)
        commands = self.root / 'commands'
        commands.mkdir()
        for name in ('bash', 'dirname', 'mkdir', 'cat', 'mv', 'rm', 'cp', 'chmod', 'mktemp', 'tar', 'gzip'):
            (commands / name).symlink_to(shutil.which(name))
        self.script(commands / 'uname', 'case "$1" in -s) echo "${BOOTSTRAP_OS:-Linux}";; -m) echo "${BOOTSTRAP_ARCH:-x86_64}";; esac')
        if shutil.which('sha256sum'):
            (commands / 'sha256sum').symlink_to(shutil.which('sha256sum'))
        else:
            (commands / 'shasum').symlink_to(shutil.which('shasum'))
            self.script(commands / 'sha256sum', 'exec shasum -a 256 "$@"')
        self.script(commands / 'curl', '''echo download >> "$BOOTSTRAP_LOG"
while [ "$#" -gt 0 ]; do
    case "$1" in https://*) source="${1#https://fixture/}";; --output) shift; output="$1";; esac
    shift
done
cp "$BOOTSTRAP_FIXTURE/$source" "$output"''')
        for name in ('python', 'python3'):
            self.script(commands / name, 'echo forbidden >> "$BOOTSTRAP_LOG"; exit 97')
        binary = b'#!/bin/sh\necho dotnet >> "$BOOTSTRAP_LOG"\n'
        archive = self.root / 'sdk.tar.gz'
        with tarfile.open(archive, 'w:gz') as value:
            member = tarfile.TarInfo('dotnet'); member.size = len(binary); member.mode = 0o755
            value.addfile(member, io.BytesIO(binary))
        bazel = self.root / 'bazel'; bazel.write_bytes(b'#!/bin/sh\nexit 0\n')
        self.hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                       for name, path in [('dotnet', archive), ('bazelisk', bazel)]}
        (scripts / 'toolchain-pins.sh').write_text('\n'.join(
            f'{name}_version=test\n{name}_url=https://fixture/{filename}\n{name}_sha256={self.hashes[name]}'
            for name, filename in [('dotnet', 'sdk.tar.gz'), ('bazelisk', 'bazel')]) + '\n')
        self.log = self.root / 'log'
        self.env = dict(os.environ, PATH=str(commands), BOOTSTRAP_FIXTURE=str(self.root), BOOTSTRAP_LOG=str(self.log))
        for key in ('RULES_MSBUILD_DOTNET_ROOT', 'RULES_MSBUILD_BAZEL', 'RULES_MSBUILD_CONTAINER_PREBUILT'):
            self.env.pop(key, None)

    def script(self, path, body):
        path.write_text('#!/bin/sh\nset -eu\n' + body + '\n'); path.chmod(0o755)

    def run_setup(self):
        return subprocess.run(['/bin/bash', 'scripts/setup.sh', '--toolchain-only'], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=30)

    def test_installs_verified_tools_and_repeat_skips_download(self):
        first = self.run_setup(); self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(os.access(self.root / '.tools/dotnet/dotnet', os.X_OK))
        self.assertTrue(os.access(self.root / '.tools/bin/bazelisk', os.X_OK))
        for name, expected in self.hashes.items():
            self.assertEqual((self.root / f'.tools/{name}.sha256').read_text().strip(), expected)
        second = self.run_setup(); self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.log.read_text().count('download'), 2)
        self.assertNotIn('forbidden', self.log.read_text())

    def test_corrupt_download_is_rejected_before_install(self):
        (self.root / 'sdk.tar.gz').write_bytes(b'corrupt')
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Checksum mismatch for dotnet', result.stderr)
        self.assertFalse((self.root / '.tools/dotnet').exists())
        self.assertFalse((self.root / '.cache/downloads' / self.hashes['dotnet']).exists())
        self.assertNotIn('dotnet', self.log.read_text())

    def test_macos_bootstrap_uses_portable_extraction_and_checksums(self):
        self.env.update(BOOTSTRAP_OS='Darwin', BOOTSTRAP_ARCH='arm64')
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root/'.tools/dotnet/dotnet').is_file())
        self.assertTrue((self.root/'.tools/bin/bazelisk').is_file())
