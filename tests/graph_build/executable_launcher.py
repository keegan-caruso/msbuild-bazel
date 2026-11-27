"""Focused execution controls for the generated, SDK-independent launcher."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import sys
import subprocess
from types import SimpleNamespace as NS

from fixture_host import temporary_directory, WINDOWS, bazel_environment, bazel_startup

ROOT = Path(__file__).resolve().parents[2]


def bash_executable():
    executable = os.environ.get('RULES_MSBUILD_BASH') or os.environ.get('BAZEL_SH') or shutil.which('bash')
    if not executable:
        raise ValueError('Set RULES_MSBUILD_BASH or BAZEL_SH to the real Bash executable')
    return executable


def bash_command(*arguments):
    values = [bash_executable(), *map(str, arguments)]
    if not WINDOWS:
        return values
    # MSYS parses bare apostrophes when launched by a native process. Force
    # Windows double quotes for every argv element, preserving empty arguments.
    quoted = []
    for value in values:
        argument = subprocess.list2cmdline([value])
        if not (argument.startswith('"') and argument.endswith('"')):
            trailing = len(argument) - len(argument.rstrip('\\'))
            argument = '"' + argument + '\\' * trailing + '"'
        quoted.append(argument)
    return ' '.join(quoted)


def bash_path(path):
    if not WINDOWS:
        return str(path)
    return subprocess.check_output(bash_command('-c', 'cygpath -au "$1"', '--', path), text=True).strip()


def shell_command(script, *arguments):
    return bash_command(script, *arguments) if WINDOWS else [str(script), *arguments]


class Files(list):
    def to_list(self):
        return self


def pinned_runfiles_library(arguments):
    if arguments.runfiles_library:
        return Path(arguments.runfiles_library).resolve(strict=True)
    command = bazel_startup('--batch')
    if arguments.bazel_output_root:
        command.append('--output_user_root=' + str(Path(arguments.bazel_output_root).resolve()))
    def bazel(*args):
        result = subprocess.run(command + list(args), cwd=ROOT, env=bazel_environment(), text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()
    files = bazel('cquery', '@rules_shell//shell/runfiles:runfiles.bash', '--output=files', '--lockfile_mode=off').splitlines()
    assert len(files) == 1, files
    return (Path(bazel('info', 'output_base')) / files[0]).resolve(strict=True)


def manifest_escape(value, key=False):
    escaped = str(value).replace('\\', '\\b').replace('\n', '\\n')
    return escaped.replace(' ', '\\s') if key else escaped


def runfiles_controls(scope, root, library):
    key = 'bazel_tools/tools/bash/runfiles/runfiles.bash'
    directory = root / 'library tree'
    (directory / key).parent.mkdir(parents=True)
    shutil.copyfile(library, directory / key)
    physical = root / 'payload space'
    physical.write_text('payload')
    logical = 'repo/escaped key'
    (directory / 'repo').mkdir()
    shutil.copyfile(physical, directory / logical)
    script = root / 'lookup'
    ctx = NS(actions=NS(write=lambda output, content, **kwargs: output.write_text(content)))
    scope['write_shell_script'](ctx, script, 'resolve_runfile "$1"\nprintf "%s\\0%s\\0%s\\0" "$RULES_MSBUILD_RESOLVED_RUNFILE" "$RULES_MSBUILD_NATIVE_RUNFILE" "$runfiles_context"\n')
    script.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('RUNFILES_', 'TEST_SRCDIR'))}
    def lookup(env, expected, context, name=logical):
        result = subprocess.run(shell_command(script, name), cwd=root, env=dict(environment, **env), capture_output=True)
        assert result.returncode == 0, result.stderr
        native = Path(expected).as_posix() if WINDOWS else str(expected)
        native_context = Path(context).as_posix() if WINDOWS else str(context)
        assert result.stdout.split(b'\0') == [os.fsencode(bash_path(expected)), os.fsencode(native), os.fsencode(native_context), b''], result.stdout
    lookup({'RUNFILES_DIR': str(directory)}, directory / logical, directory)
    lookup({'TEST_SRCDIR': directory.name}, directory / logical, directory)
    adjacent_tree = Path(str(script) + '.runfiles')
    shutil.copytree(directory, adjacent_tree)
    lookup({}, adjacent_tree / logical, adjacent_tree)
    shutil.rmtree(adjacent_tree)
    manifest = root / 'lookup manifest'
    bootstrap = root / ('bootstrap library space.bash' if WINDOWS else 'bootstrap library space\\name.bash')
    shutil.copyfile(library, bootstrap)
    def write_manifest(target, entry=physical):
        manifest.write_bytes((' ' + key + ' ' + manifest_escape(target) + '\n ' + manifest_escape(logical, key=True) + ' ' + manifest_escape(entry) + '\n').encode())
    write_manifest(bootstrap)
    lookup({'RUNFILES_MANIFEST_FILE': manifest.name, 'RUNFILES_MANIFEST_ONLY': '1'}, physical, manifest)
    # Discover the manifest adjacent to the script without environment hints.
    adjacent = Path(str(script) + '.runfiles_manifest')
    shutil.copyfile(manifest, adjacent)
    lookup({}, physical, adjacent)
    adjacent.unlink()
    missing = subprocess.run(shell_command(script, 'repo/missing'), cwd=root, env=dict(environment, RUNFILES_MANIFEST_FILE=str(manifest)), capture_output=True)
    assert missing.returncode != 0 and b'missing runfile' in missing.stderr, missing
    if os.name != 'nt':
        newline = root / 'payload ending\n'
        newline.write_text('payload')
        write_manifest(bootstrap, newline)
        lookup({'RUNFILES_MANIFEST_FILE': str(manifest)}, newline, manifest)
        trailing_library = root / 'library ending\n'
        shutil.copyfile(library, trailing_library)
        write_manifest(trailing_library, newline)
        lookup({'RUNFILES_MANIFEST_FILE': str(manifest)}, newline, manifest)
    write_manifest(bootstrap)
    adjacent = Path(str(script) + '.exe.runfiles_manifest')
    shutil.copyfile(manifest, adjacent)
    lookup({}, physical, adjacent)
    adjacent.unlink()
    if WINDOWS:
        print('UNRUN: POSIX trailing-newline physical filename controls')
    print('PASS: production Bash prelude with pinned runfiles library, directory/manifest lookup, escaped keys/bootstrap paths and missing runfiles')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runfiles-library', help='Already resolved rules_shell0.6.1 runfiles.bash; defaults to a bounded Bazel cquery')
    parser.add_argument('--bazel-output-root', help='Optional disposable Bazel output user root for library discovery')
    arguments = parser.parse_args()
    library = pinned_runfiles_library(arguments)
    print("Using pinned runfiles library SHA256=" + hashlib.sha256(library.read_bytes()).hexdigest(), flush=True)
    # Execute the production writer/prelude. Only PE/provider metadata is stubbed;
    # manifest lookup always comes from the actual pinned rules_shell library.
    shell_scope = {'Label': lambda label: label}
    source = (ROOT / 'msbuild/private/shell_launcher.bzl').read_text()
    exec('\n'.join(line for line in source.splitlines() if not line.startswith('load(')), shell_scope)
    source = (ROOT / 'msbuild/private/project_launch.bzl').read_text()
    scope = {}
    exec('\n'.join(line for line in source.splitlines() if not line.startswith('load(')), scope)
    scope.update(_quote=lambda s: "'" + s.replace("'", "'\"'\"'") + "'",
                 _runfile=lambda ctx, file: str(file),
                 depset=lambda files: files, DefaultInfo=lambda **kw: kw,
                 RunEnvironmentInfo=lambda **kw: kw,
                 shell_launcher=lambda ctx, script: script,
                 shell_runfiles=lambda ctx, **kwargs: kwargs,
                 write_shell_script=shell_scope['write_shell_script'])
    with temporary_directory(prefix='launcher-control-') as temporary:
        root = Path(temporary).resolve()
        runfiles = root / 'runfiles space'
        library_target = runfiles / 'bazel_tools/tools/bash/runfiles/runfiles.bash'
        library_target.parent.mkdir(parents=True)
        shutil.copyfile(library, library_target)
        app = runfiles / 'app'
        app.mkdir(parents=True)
        (app / 'App.dll').write_text('assembly')
        (app / '.hidden').write_text('hidden')
        (app / '.hidden').chmod(0o755)
        (app / 'App.dll').chmod(0o444)
        host_root = runfiles / 'host'
        host_root.mkdir()
        host = host_root / 'host'
        probe = host.with_suffix('.py') if WINDOWS else host
        probe.write_text('''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
if "hang" in sys.argv:
    if os.environ.get("HOST_PID_FILE"):
        pathlib.Path(os.environ["HOST_PID_FILE"]).write_text(str(os.getpid()))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pathlib.Path(os.environ["PID_FILE"]).write_text(str(child.pid))
    time.sleep(60)
if "write" in sys.argv:
    pathlib.Path("App.dll").write_text("changed")
    pathlib.Path(".hidden").write_text("changed")
    pathlib.Path("../results with space/nested/file").write_text("output")
if "copyfail" in sys.argv:
    target = pathlib.Path(os.environ["TEST_UNDECLARED_OUTPUTS_DIR"]) / "files/results with space/nested"
    target.rmdir()
    target.write_text("collision")
print(json.dumps(dict(args=sys.argv[1:], cwd=os.getcwd(), stdin=sys.stdin.read(), executable=os.access(".hidden", os.X_OK), root=os.environ["DOTNET_ROOT"], core=os.environ.get("CORE_ROOT"), custom=os.environ["CUSTOM"])))
sys.exit(7 if "seven" in sys.argv else 0)
''')
        if WINDOWS:
            host.write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(bash_path(sys.executable)) + ' ' + shlex.quote(probe.as_posix()) + ' "$@"\n')
        host.chmod(0o755)
        declared = NS(directory='host', entry_point='host', launch_mode='dotnet', environment={'CUSTOM': "space ' $value"}, files=Files(['host', 'host.py'] if WINDOWS else ['host']))
        scope['_runtime_host'] = lambda ctx: declared
        script = root / 'launcher'
        actions = NS(declare_file=lambda name: script, write=lambda file, content, **kw: file.write_text(content))
        attrs = dict(direct_executable_smoke=False, test_settings=None, test_settings_output='', test_output_dirs=[], test_working_directory='', expected_exit_code=0, env={}, test_protocol='executable', test_filter_argument='', allow_empty_tests=False, test_diagnostics=False, test_runner=None, test_adapters=[], data_paths={})

        def generate(test=True, data=()):
            ctx = NS(attr=NS(**attrs), label=NS(name='launcher'), actions=actions, runfiles=lambda **kw: kw)
            scope['create_executable_launcher'](ctx, 'App.dll', 'app', Files(data), test)
            script.chmod(0o755)
            subprocess.run(bash_command('-n', script), check=True)

        environment = dict(os.environ, RUNFILES_DIR=str(runfiles), CORE_ROOT='ambient')
        for key in ('TESTBRIDGE_TEST_ONLY', 'TEST_TOTAL_SHARDS', 'TEST_SHARD_INDEX', 'RUNFILES_MANIFEST_FILE', 'RUNFILES_MANIFEST_ONLY', 'TEST_SRCDIR'):
            environment.pop(key, None)

        def run(args=(), code=0, extra=None):
            result = subprocess.run(shell_command(script, *args), env=dict(environment, **(extra or {})), input='stdin payload', text=True, capture_output=True, cwd=root)
            assert result.returncode == code, result.stdout + result.stderr
            return result

        generate(False)
        observed = json.loads(run(['space argument', '', '$HOME', "a'b"]).stdout)
        assert observed['args'][1:] == ['space argument', '', '$HOME', "a'b"], observed
        if WINDOWS:
            print('UNRUN: POSIX executable-bit control; Windows file mode does not express it')
        else:
            assert observed['executable'], observed
        assert observed['stdin'] == 'stdin payload' and observed['core'] is None and observed['custom'] == "space ' $value", observed
        assert not Path(observed['cwd']).exists()
        run(['seven'], 7)
        attrs.update(test_working_directory='work', test_output_dirs=['results with space/nested'], expected_exit_code=7)
        generate()
        output = root / 'outputs'
        run(['write', 'seven'], extra={'TEST_UNDECLARED_OUTPUTS_DIR': str(output)})
        assert (output / 'files/results with space/nested/file').read_text() == 'output'
        assert (app / 'App.dll').read_text() == 'assembly'
        if WINDOWS:
            failure = run(['write', 'seven', 'copyfail'], code=1,
                          extra={'TEST_UNDECLARED_OUTPUTS_DIR': str(root / 'failed-outputs')})
            assert 'Failed to collect test output directories' in failure.stderr, failure
            assert not Path(json.loads(failure.stdout)['cwd']).exists(), failure
            assert (root / 'failed-outputs/files/results with space/nested').read_text() == 'collision'
            print('PASS: Windows copy-out failure preserves failure status and removes private runtime')
        run(code=1)
        run(extra={'TESTBRIDGE_TEST_ONLY': 'filter'}, code=1)
        declared.launch_mode = 'corerun'
        attrs.update(test_working_directory='', test_output_dirs=[], expected_exit_code=0)
        generate()
        assert Path(json.loads(run().stdout)['core']).resolve() == host_root.resolve()
        generate(data=[NS(file='app/.hidden', destination='App.dll')])
        assert 'Conflicting' in run(code=1).stderr
        generate()
        pid_file = root / 'pid'
        signal_pid = root / 'signal-pid'
        host_pid = root / 'host-pid'
        command = shell_command(script, 'hang')
        cancellation_environment = dict(environment, PID_FILE=str(pid_file), CONTROL_PID_FILE=str(signal_pid), HOST_PID_FILE=str(host_pid))
        if WINDOWS:
            # Observe the generated Bash itself, without inserting an execing
            # shell between it and the native process-status observer.
            observer = root / 'signal-observer'
            observer.write_text('case "$0" in */launcher|*\\\\launcher) printf "%s" "$$" > "$CONTROL_PID_FILE" ;; esac\n', newline='\n')
            cancellation_environment['BASH_ENV'] = bash_path(observer)
        process = subprocess.Popen(command, env=cancellation_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import time
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert pid_file.exists()
        if WINDOWS:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel.WaitForSingleObject.restype = ctypes.c_uint32
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            children = [kernel.OpenProcess(0x100001, False, int(file.read_text())) for file in (host_pid, pid_file)]
            sibling = None
            try:
                assert all(children), 'Cannot observe native host and child processes'
                sibling = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(bash_command('-c', 'kill -TERM "$1"', '--', signal_pid.read_text()), check=True)
                stdout, stderr = process.communicate(timeout=5)
                assert process.returncode == 143, (process.returncode, stdout, stderr)
                assert all(kernel.WaitForSingleObject(child, 5000) == 0 for child in children), 'Native host or child survived launcher cancellation'
                assert sibling.poll() is None, 'Cancellation terminated an unrelated native sibling'
                print('PASS: native cancellation reaps owned host/child and leaves unrelated sibling alive')
            finally:
                if process.poll() is None:
                    process.kill()
                for child in children:
                    if child:
                        if kernel.WaitForSingleObject(child, 0) != 0:
                            kernel.TerminateProcess(child, 125)
                            kernel.WaitForSingleObject(child, 5000)
                        kernel.CloseHandle(child)
                if sibling is not None:
                    sibling.kill()
                    sibling.wait(timeout=5)
                process.communicate(timeout=5)
        else:
            process.send_signal(signal.SIGTERM)
            process.communicate(timeout=5)
            assert process.returncode == 143
            state = subprocess.run(['ps', '-o', 'stat=', '-p', pid_file.read_text()], text=True, capture_output=True).stdout.strip()
            assert not state or state.startswith('Z'), state
        if WINDOWS:
            print('UNRUN: POSIX controlling-TTY and TTY-signal cases require pty.fork; native pipe/stdin and child cleanup are checked')
        else:
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
        probe.write_text(probe.read_text().replace('os.environ["CUSTOM"]', 'os.environ.get("CUSTOM")'))
        generate()
        assert Path(json.loads(run().stdout)['cwd']).resolve() == root.resolve()
        runfiles_controls(shell_scope, root, library)
    print('PASS: writable staging, hidden files, stdin, argv, host environment, dotnet/corerun, expected exits, output directories, collisions, cancellation, readonly')


if __name__ == '__main__':
    main()
