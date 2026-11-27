"""Host forwarding and guest cache configuration without starting a VM."""
import os
import shlex
from pathlib import Path
import subprocess
import socket
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/run-apple-container.sh'


class AppleContainerTests(unittest.TestCase):
    def test_prebuilt_bazelisk_survives_workspace_environment(self):
        dockerfile=(ROOT / 'containers/toolchain.Dockerfile').read_text().replace('\\\n', ' ')
        tools={}
        for line in dockerfile.splitlines():
            if line.startswith('ENV '):
                tools.update(part.split('=', 1) for part in shlex.split(line[4:]) if '=' in part)
        env=dict(os.environ, **tools)
        result=subprocess.run(['bash', '-c', 'source scripts/env.sh; printf "%s" "$RULES_MSBUILD_BAZELISK"'],
                              cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '/opt/rules_msbuild-toolchain/.tools/bin/bazelisk')

    @unittest.skipIf(os.name == 'nt', 'macOS container forwarding uses POSIX shell paths')
    def test_forwarding_and_guest_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / 'repo'
            (repo / 'scripts').mkdir(parents=True)
            script = repo / 'scripts/run-apple-container.sh'
            script.write_bytes(SCRIPT.read_bytes())
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'uname').write_text('#!/bin/bash\ncase "$1" in -s) echo Darwin;; -m) echo arm64;; esac\n')
            (tools / 'container').write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE/args"\ncat > "$CAPTURE/guest"\n')
            for tool in tools.iterdir():
                tool.chmod(0o755)
            env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'], CAPTURE=folder,
                       RULES_MSBUILD_SHARED_CACHE_URL='http://cache.invalid:8080',
                       RULES_MSBUILD_CONTAINER_PREBUILT='1', RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='1')
            env.pop('USE_BAZEL_VERSION', None)
            env.pop('RULES_MSBUILD_CONTAINER_IMAGE', None)
            env.pop('RULES_MSBUILD_CONTAINER_ARCH', None)
            result = subprocess.run(['bash', str(script), 'printf', 'done'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = (root / 'args').read_text().splitlines()
            for expected in ('--rm', 'RULES_MSBUILD_CONTAINER_PREBUILT=1',
                             'RULES_MSBUILD_SHARED_CACHE_URL=http://cache.invalid:8080',
                             'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1'):
                self.assertIn(expected, args)
            self.assertIn('USE_BAZEL_VERSION=', args)
            pin='ubuntu@sha256:065aa8626841f16057b78b027b464cd59c4fac36c204c72dcbf48d66f5fa8a96'
            self.assertIn(pin, args)
            self.assertNotIn('--rosetta', args)
            self.assertIn('libicu78 libssl3t64', (root / 'guest').read_text())
            self.assertIn('export RULES_MSBUILD_TAR=/usr/bin/bsdtar', (root / 'guest').read_text())
            self.assertIn('libarchive-tools=3.8.5-1ubuntu2.3', (root / 'guest').read_text())
            self.assertIn('FROM '+pin, (ROOT / 'containers/toolchain.Dockerfile').read_text())
            env['RULES_MSBUILD_CONTAINER_ARCH']='amd64'
            amd64=subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
            self.assertEqual(amd64.returncode, 0, amd64.stderr)
            self.assertIn('--rosetta', (root / 'args').read_text().splitlines())
            env.pop('RULES_MSBUILD_CONTAINER_ARCH')
            env['RULES_MSBUILD_CONTAINER_ACQUISITION'] = str(root / 'downloads')
            acquired = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            acquired_args = (root / 'args').read_text().splitlines()
            self.assertIn(str(root / 'downloads') + ':/acquisition', acquired_args)
            self.assertIn('RULES_MSBUILD_CONTAINER_ACQUISITION=1', acquired_args)
            self.assertIn('export BAZELISK_HOME=/acquisition/bazelisk', (root / 'guest').read_text())
            self.assertIn('ln -s /acquisition/downloads .cache/downloads', (root / 'guest').read_text())
            env.pop('RULES_MSBUILD_CONTAINER_ACQUISITION')
            env['USE_BAZEL_VERSION'] = '9.3.3'
            result = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            override_args = (root / 'args').read_text().splitlines()
            self.assertIn('USE_BAZEL_VERSION=9.3.3', override_args)
            self.assertEqual(override_args[override_args.index('USE_BAZEL_VERSION=9.3.3') - 1], '-e')
            with socket.socket(socket.AF_UNIX) as relay_socket:
                socket_path = str(root / 'host.sock')
                relay_socket.bind(socket_path)
                env['RULES_MSBUILD_SHARED_CACHE_SOCKET'] = socket_path
                env['RULES_MSBUILD_SHARED_CACHE_URL'] = 'https://cache.invalid:8443'
                result = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                relay_args = (root / 'args').read_text().splitlines()
                self.assertIn(socket_path + ':/var/host-services/shared-cache.sock', relay_args)
                self.assertIn('RULES_MSBUILD_SHARED_CACHE_RELAY=1', relay_args)
                env['RULES_MSBUILD_SHARED_CACHE_URL'] = 'http://cache.invalid:18726'
                rejected = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
                self.assertEqual(rejected.returncode, 2)
                self.assertIn(b'RULES_MSBUILD_SHARED_CACHE_ALLOW_HTTP', rejected.stderr)
                env['RULES_MSBUILD_SHARED_CACHE_ALLOW_HTTP'] = '1'
                allowed = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
                self.assertEqual(allowed.returncode, 0, allowed.stderr)
                self.assertIn('RULES_MSBUILD_SHARED_CACHE_ALLOW_HTTP=1', (root / 'args').read_text())
                env.pop('RULES_MSBUILD_SHARED_CACHE_ALLOW_HTTP')
            env.pop('RULES_MSBUILD_SHARED_CACHE_SOCKET')
            env['RULES_MSBUILD_SHARED_CACHE_URL'] = 'http://cache.invalid:8080'
            guest = (root / 'guest').read_text()
            start = guest.index('if [[ -n "${RULES_MSBUILD_SHARED_CACHE_URL')
            configuration = guest[start:guest.index('if [[ "${RULES_MSBUILD_CONTAINER_PREBUILT', start)]
            env['HOME'] = folder
            subprocess.run(['bash', '-eu', '-c', configuration], env=env, check=True)
            rc = (root / '.bazelrc').read_text()
            self.assertIn('build --remote_cache=http://cache.invalid:8080\n', rc)
            self.assertIn('build --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache.invalid:8080\n', rc)
            self.assertIn('build --action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1\n', rc)
            for option in ('--jobs=2', '--worker_max_instances=MSBuildGraph=1', '--local_test_jobs=1', '--disk_cache=', '--remote_download_outputs=all'):
                self.assertIn(option + '\n', rc)
            (root / '.bazelrc').unlink()
            env['RULES_MSBUILD_SHARED_CACHE_URL'] = ''
            subprocess.run(['bash', '-eu', '-c', configuration], env=env, check=True)
            self.assertFalse((root / '.bazelrc').exists())
            for invalid_url in ('http://cache.invalid/ with space', r'http://cache.invalid/single\slash'):
                with self.subTest(url=invalid_url):
                    env['RULES_MSBUILD_SHARED_CACHE_URL'] = invalid_url
                    result = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
                    self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main()
