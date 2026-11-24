"""Execute the actual qualification pack action and relocated launcher."""
import os
import json
from pathlib import Path
import shutil
import shlex
import sys
import signal
import subprocess
import tempfile
import tarfile
import types
import unittest


class PackedRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(__import__('sys').version_info >= (3, 14), 'packing requires Python 3.14')
    def test_relocation_environment_exit_and_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'original'
            source.mkdir()
            host = source / 'dotnet'
            host.write_text('''#!/usr/bin/env bash
set -eu
[[ "$DOTNET_ROOT" = "$(dirname "$0")" ]]
[[ "$DOTNET_HOST_PATH" = "$0" ]]
[[ "$DOTNET_ROOT_ARM64" = "$DOTNET_ROOT" ]]
[[ "$DOTNET_MULTILEVEL_LOOKUP" = 0 ]]
[[ "$PRESERVED" = yes ]]
[[ "$(cat "$DOTNET_ROOT/shared/framework/runtime.txt")" = declared-runtime ]]
if [[ \"$1\" = signal ]]; then
  trap 'exit 130' INT
  trap 'exit 143' TERM
  echo ready
  while true; do read -r -t 1 ignored || true; done
fi
read -r input
[[ \"$input\" = stdin-preserved ]]
printf '%s\\n' "$DOTNET_ROOT" "$1"
exit 23
''')
            host.chmod(0o755)
            framework = source / 'shared' / 'framework'
            framework.mkdir(parents=True)
            (framework / 'runtime.txt').write_text('declared-runtime')
            # Bazel sandbox tree artifacts may contain absolute file symlinks,
            # while an entire input directory may itself be a sandbox symlink.
            sandbox = root / 'sandbox'
            sandbox.mkdir()
            (sandbox / 'dotnet').symlink_to(host)
            (sandbox / 'shared').mkdir()
            (sandbox / 'shared' / 'framework').symlink_to(framework, target_is_directory=True)
            sandbox_input = root / 'sandbox-input'
            sandbox_input.symlink_to(sandbox, target_is_directory=True)
            output = root / 'packed'
            class Actions:
                def declare_directory(self, name):
                    return types.SimpleNamespace(path=str(output))
                def declare_file(self, name):
                    return types.SimpleNamespace(path=str(root / name))
                def write(self, file, body, **kwargs):
                    Path(file.path).write_text(body.replace("#!/usr/bin/env python3", "#!" + sys.executable))
                def run_shell(self, **kwargs):
                    subprocess.run(['bash', '-c', kwargs['command'].replace('python3 -', shlex.quote(sys.executable) + ' -'), 'pack', *kwargs['arguments']], check=True)
            provider = object()
            namespace = dict(json=types.SimpleNamespace(encode=json.dumps), load=lambda *a: None, rule=lambda **k: None,
                             attr=types.SimpleNamespace(label=lambda **k: None),
                             MSBuildRuntimeInfo=provider, depset=lambda *a, **k: None,
                             DefaultInfo=lambda **k: None)
            exec(Path(__file__).with_name('runtime_pack.bzl').read_text(), namespace)
            runtime = types.SimpleNamespace(directory=types.SimpleNamespace(path=str(sandbox_input)),
                                            files=[], entry_point='dotnet', launch_mode='dotnet',
                                            runtime_identifier='linux-arm64', version='11.0.0', environment={})
            namespace['MSBuildRuntimeInfo'] = lambda **k: k
            runtime_key = namespace['MSBuildRuntimeInfo']
            ctx = types.SimpleNamespace(actions=Actions(), label=types.SimpleNamespace(name='packed'),
                                        attr=types.SimpleNamespace(runtime={runtime_key: runtime}))
            namespace['_packed_runtime'](ctx)
            with tarfile.open(output / 'runtime.tar.zst', 'r:zst') as archive:
                self.assertTrue(all(not entry.issym() and not entry.islnk() for entry in archive))
            shutil.rmtree(source)
            shutil.rmtree(sandbox)
            sandbox_input.unlink()
            relocated = root / 'relocated runtime'
            output.rename(relocated)
            scratch = root / 'scratch'
            scratch.mkdir()
            for _ in range(2):
                result = subprocess.run([str(relocated / 'launch'), 'argument with spaces'],
                                        env={**os.environ, 'TEST_TMPDIR': str(scratch), 'PRESERVED': 'yes'},
                                        capture_output=True, text=True, input='stdin-preserved\n')
                self.assertEqual(result.returncode, 23, result.stderr)
                self.assertEqual(result.stdout.splitlines()[1], 'argument with spaces')
                self.assertEqual(list(scratch.iterdir()), [])

            for signum in [signal.SIGINT, signal.SIGTERM]:
                child = subprocess.Popen([str(relocated / 'launch'), 'signal'],
                    env={**os.environ, 'TEST_TMPDIR': str(scratch), 'PRESERVED': 'yes'},
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                child.send_signal(signum)
                self.assertEqual(child.wait(timeout=10), 128 + signum)
                child.stdin.close()
                child.stdout.close()
                self.assertEqual(list(scratch.iterdir()), [])
