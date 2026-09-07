"""Keep Bazel servers alive within a probe and shut every output base down afterward."""
import os
from pathlib import Path
import subprocess
import sys


class BazelSession:
    def __init__(self, output, mode=None):
        self.output = Path(output)
        self.mode = mode or os.environ.get('RULES_MSBUILD_BAZEL_MODE', 'server')
        if self.mode not in ('batch', 'server'):
            raise ValueError('RULES_MSBUILD_BAZEL_MODE must be batch or server')
        self.servers = {}

    def __enter__(self):
        return self

    def prepare(self, command, cwd, env):
        command = [str(arg) for arg in command]
        if self.mode == 'batch':
            return command
        command = [arg for arg in command if arg != '--batch']
        command.insert(1, '--max_idle_secs=120')
        index = next(i for i, arg in enumerate(command) if arg in ('build', 'clean', 'version'))
        prefix = tuple(command[:index])
        self.servers[prefix] = (cwd, dict(env))
        return command

    def __exit__(self, exception_type, exception, traceback):
        errors = []
        for index, (prefix, (cwd, env)) in enumerate(reversed(list(self.servers.items()))):
            try:
                result = subprocess.run([*prefix, 'shutdown'], cwd=cwd, env=env,
                                        text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, timeout=60)
                (self.output / f'bazel-shutdown-{index}.log').write_text(result.stdout)
                if result.returncode:
                    errors.append(f'shutdown returned {result.returncode}: {prefix}')
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        self.servers.clear()
        if errors:
            message = 'Bazel server cleanup failed: ' + '; '.join(errors)
            if exception is None:
                raise RuntimeError(message)
            print(message, file=sys.stderr)
        return False
