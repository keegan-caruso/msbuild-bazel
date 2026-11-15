"""Host forwarding and guest cache configuration without starting a VM."""
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/run-apple-container.sh'


class AppleContainerTests(unittest.TestCase):
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
            self.assertIn('FROM '+pin, (ROOT / 'containers/toolchain.Dockerfile').read_text())
            env['RULES_MSBUILD_CONTAINER_ARCH']='amd64'
            amd64=subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
            self.assertEqual(amd64.returncode, 0, amd64.stderr)
            self.assertIn('--rosetta', (root / 'args').read_text().splitlines())
            env.pop('RULES_MSBUILD_CONTAINER_ARCH')
            env['USE_BAZEL_VERSION'] = '9.3.2'
            result = subprocess.run(['bash', str(script), 'true'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            override_args = (root / 'args').read_text().splitlines()
            self.assertIn('USE_BAZEL_VERSION=9.3.2', override_args)
            self.assertEqual(override_args[override_args.index('USE_BAZEL_VERSION=9.3.2') - 1], '-e')
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
