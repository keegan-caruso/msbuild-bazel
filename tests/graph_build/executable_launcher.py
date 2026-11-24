"""Focused execution controls for the generated, SDK-independent launcher."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]


class Files(list):
    def to_list(self):
        return self


def main():
    source = (ROOT / 'msbuild/private/project_launch.bzl').read_text()
    scope = {}
    exec('\n'.join(line for line in source.splitlines() if not line.startswith('load(')), scope)
    scope.update(_quote=lambda s: "'" + s.replace("'", "'\"'\"'") + "'",
                 _runfile=lambda ctx, file: str(file),
                 depset=lambda files: files, DefaultInfo=lambda **kw: kw,
                 RunEnvironmentInfo=lambda **kw: kw)
    with tempfile.TemporaryDirectory(prefix='launcher-control-') as temporary:
        root = Path(temporary)
        runfiles = root / 'runfiles space'
        app = runfiles / 'app'
        app.mkdir(parents=True)
        (app / 'App.dll').write_text('assembly')
        (app / '.hidden').write_text('hidden')
        (app / '.hidden').chmod(0o755)
        (app / 'App.dll').chmod(0o444)
        host_root = runfiles / 'host'
        host_root.mkdir()
        host = host_root / 'host'
        host.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
if "hang" in sys.argv:
    child = subprocess.Popen(["sleep", "60"])
    pathlib.Path(os.environ["PID_FILE"]).write_text(str(child.pid))
    time.sleep(60)
if "write" in sys.argv:
    pathlib.Path("App.dll").write_text("changed")
    pathlib.Path(".hidden").write_text("changed")
    pathlib.Path("../results/file").write_text("output")
print(json.dumps(dict(args=sys.argv[1:], cwd=os.getcwd(), stdin=sys.stdin.read(), executable=os.access(".hidden", os.X_OK), root=os.environ["DOTNET_ROOT"], core=os.environ.get("CORE_ROOT"), custom=os.environ["CUSTOM"])))
sys.exit(7 if "seven" in sys.argv else 0)
''')
        host.chmod(0o755)
        declared = NS(directory='host', entry_point='host', launch_mode='dotnet', environment={'CUSTOM': "space ' $value"}, files=Files(['host']))
        scope['_runtime_host'] = lambda ctx: declared
        script = root / 'launcher'
        actions = NS(declare_file=lambda name: script, write=lambda file, content, **kw: file.write_text(content))
        attrs = dict(direct_executable_smoke=False, test_settings=None, test_settings_output='', test_output_dirs=[], test_working_directory='', expected_exit_code=0, env={}, test_protocol='executable', test_filter_argument='', allow_empty_tests=False, test_diagnostics=False, test_runner=None, test_adapters=[], data_paths={})

        def generate(test=True, data=()):
            ctx = NS(attr=NS(**attrs), label=NS(name='launcher'), actions=actions, runfiles=lambda **kw: kw)
            scope['create_executable_launcher'](ctx, 'App.dll', 'app', Files(data), test)
            script.chmod(0o755)
            subprocess.run(['bash', '-n', str(script)], check=True)

        environment = dict(os.environ, RUNFILES_DIR=str(runfiles), CORE_ROOT='ambient')
        for key in ('TESTBRIDGE_TEST_ONLY', 'TEST_TOTAL_SHARDS', 'TEST_SHARD_INDEX'):
            environment.pop(key, None)

        def run(args=(), code=0, extra=None):
            result = subprocess.run([str(script), *args], env=dict(environment, **(extra or {})), input='stdin payload', text=True, capture_output=True, cwd=root)
            assert result.returncode == code, result.stdout + result.stderr
            return result

        generate(False)
        observed = json.loads(run(['space argument', '', '$HOME', "a'b"]).stdout)
        assert observed['args'][1:] == ['space argument', '', '$HOME', "a'b"], observed
        assert observed['executable'], observed
        assert observed['stdin'] == 'stdin payload' and observed['core'] is None and observed['custom'] == "space ' $value", observed
        assert not Path(observed['cwd']).exists()
        run(['seven'], 7)
        attrs.update(test_working_directory='work', test_output_dirs=['results'], expected_exit_code=7)
        generate()
        output = root / 'outputs'
        run(['write', 'seven'], extra={'TEST_UNDECLARED_OUTPUTS_DIR': str(output)})
        assert (output / 'files/results/file').read_text() == 'output'
        assert (app / 'App.dll').read_text() == 'assembly'
        run(code=1)
        run(extra={'TESTBRIDGE_TEST_ONLY': 'filter'}, code=1)
        declared.launch_mode = 'corerun'
        attrs.update(test_working_directory='', test_output_dirs=[], expected_exit_code=0)
        generate()
        assert json.loads(run().stdout)['core'] == str(host_root)
        generate(data=[NS(file='app/.hidden', destination='App.dll')])
        assert 'Conflicting' in run(code=1).stderr
        generate()
        pid_file = root / 'pid'
        process = subprocess.Popen([str(script), 'hang'], env=dict(environment, PID_FILE=str(pid_file)), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import time
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert pid_file.exists()
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        assert process.returncode == 143
        pid = pid_file.read_text()
        state = subprocess.run(['ps', '-o', 'stat=', '-p', pid], text=True, capture_output=True).stdout.strip()
        assert not state or state.startswith('Z'), state
        # A real controlling TTY exercises foreground handoff and terminal stdin.
        import pty
        import select
        generate(False)
        tty_pid, terminal = pty.fork()
        if tty_pid == 0:
            os.execve(str(script), [str(script), 'tty'], environment)
        os.write(terminal, b'terminal payload\n\x04')
        transcript = b''
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if select.select([terminal], [], [], .1)[0]:
                try:
                    chunk = os.read(terminal, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                transcript += chunk
        waited, status = os.waitpid(tty_pid, os.WNOHANG)
        if not waited:
            os.kill(tty_pid, signal.SIGKILL)
            os.close(terminal)
            os.waitpid(tty_pid, 0)
            raise AssertionError('TTY launcher hung: ' + repr(transcript))
        os.close(terminal)
        assert os.waitstatus_to_exitcode(status) == 0, transcript
        assert b'"stdin": "terminal payload\\n"' in transcript, transcript
        pid_file.unlink()
        tty_pid, terminal = pty.fork()
        if tty_pid == 0:
            os.execve(str(script), [str(script), 'hang'], dict(environment, PID_FILE=str(pid_file)))
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert pid_file.exists()
        os.kill(tty_pid, signal.SIGTERM)
        while time.monotonic() < deadline:
            if select.select([terminal], [], [], .1)[0]:
                try:
                    if not os.read(terminal, 65536):
                        break
                except OSError:
                    break
        waited, status = os.waitpid(tty_pid, os.WNOHANG)
        if not waited:
            os.kill(tty_pid, signal.SIGKILL)
            os.close(terminal)
            os.waitpid(tty_pid, 0)
            raise AssertionError('TTY cancellation hung')
        os.close(terminal)
        assert os.waitstatus_to_exitcode(status) == 143, status
        state = subprocess.run(['ps', '-o', 'stat=', '-p', pid_file.read_text()], text=True, capture_output=True).stdout.strip()
        assert not state or state.startswith('Z'), state
        attrs['direct_executable_smoke'] = True
        declared.launch_mode = 'dotnet'
        declared.environment = {}
        host.write_text(host.read_text().replace('os.environ["CUSTOM"]', 'os.environ.get("CUSTOM")'))
        generate()
        assert Path(json.loads(run().stdout)['cwd']).resolve() == root.resolve()
    print('PASS: writable staging, hidden files, stdin, argv, host environment, dotnet/corerun, expected exits, output directories, collisions, cancellation, readonly')


if __name__ == '__main__':
    main()
