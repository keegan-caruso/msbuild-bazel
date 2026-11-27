"""Bounded native macOS public Bazel worker parity and cancellation qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import time
import uuid


def records(path):
    text = path.read_text(); decoder = json.JSONDecoder()
    while text.strip():
        row, used = decoder.raw_decode(text.lstrip())
        yield row
        text = text.lstrip()[used:]


def processes():
    rows = subprocess.check_output(['/bin/ps', '-axww', '-o', 'pid=,ppid=,command='], text=True, timeout=5)
    return {int(pid): (int(parent), command) for line in rows.splitlines()
            if len(parts := line.strip().split(None, 2)) == 3 for pid, parent, command in [parts]}


def identity(pid):
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart='], text=True, capture_output=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def products(workspace):
    files = sorted({p for project in workspace.glob('P*') for pattern in
                    ('bin/Release/**/*', 'obj/Release/**/ref/*.dll') for p in project.glob(pattern) if p.is_file()})
    result = {p.relative_to(workspace).as_posix(): [hashlib.sha256(p.read_bytes()).hexdigest(),
              stat.S_IMODE(p.stat().st_mode)] for p in files}
    for project in ('P0', 'P1', 'P2'):
        assert f'{project}/bin/Release/net11.0/{project}.dll' in result, result
    assert 'P0/obj/Release/net11.0/ref/P0.dll' in result, result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--rules', required=True, type=Path)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--bazel', required=True, type=Path)
    parser.add_argument('--repository-cache', type=Path)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    assert platform.system() == 'Darwin' and platform.machine() == 'arm64', platform.uname()
    rules = args.rules.resolve(strict=True); bazel = args.bazel.resolve(strict=True)
    revision = subprocess.check_output(['git', '-C', str(rules), 'rev-parse', 'HEAD'], text=True).strip()
    expected = subprocess.check_output(['git', '-C', str(rules), 'rev-parse', args.expected_revision], text=True).strip()
    assert revision == expected, (revision, expected)
    subprocess.run(['git', '-C', str(rules), 'diff', '--quiet', 'HEAD'], check=True)
    root = args.directory.resolve(); root.mkdir(parents=True, exist_ok=False)
    consumer = root / 'consumer'; shutil.copytree(rules / 'tests/integration/fixtures/worker', consumer)
    module = consumer / 'MODULE.bazel'
    module.write_text(module.read_text().replace('"../msbuild-bazel"', json.dumps(str(rules))))
    settings = json.loads((consumer / 'global.json').read_text()); settings['sdk']['version'] = '11.0.100'
    (consumer / 'global.json').write_text(json.dumps(settings))
    for project in consumer.glob('P*/*.csproj'):
        project.write_text(project.read_text().replace('net10.0', 'net11.0'))
    marker = 'msbuild-mac-cancel-' + uuid.uuid4().hex
    target = consumer / 'P0/Directory.Build.targets'
    target.write_text('<Project><Target Name="WorkerCancellationControl" BeforeTargets="CoreCompile">'
        '<Exec Command="/bin/bash -c &quot;/bin/sleep 600 &amp; wait&quot; '+marker+'" '
        """Condition="$([System.IO.File]::ReadAllText('$(MSBuildProjectDirectory)/Code.cs').Contains('issue224-cancel'))" />"""
        '</Target></Project>')
    (consumer / 'worker-mappings.json').write_text(json.dumps(dict(
        projectDefaults=dict(referenceBoundary=True, preparedRestore=True), projects={'P0/P0.csproj': dict(documents={
        'P0/Directory.Build.targets': dict(sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                                         targets=['WorkerCancellationControl'], tasks=[], inputs=['P0/Code.cs'])})})))
    build = consumer / 'BUILD.bazel'
    build.write_text((consumer / 'BUILD.bazel.in').read_text().replace(
        'projects = ["P2/P2.csproj"]', 'projects = ["P2/P2.csproj"], mappings = "worker-mappings.json"'))
    environment = dict(os.environ, USE_BAZEL_VERSION=(rules / '.bazelversion').read_text().strip())
    for key in ('RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN'):
        environment.pop(key, None)
    base = root / 'bazel'
    startup = [str(bazel), '--ignore_all_rc_files', '--output_base=' + str(base)]
    options = ['--override_module=rules_msbuild=' + str(rules), '--jobs=2', '--worker_max_instances=MSBuildGraph=1']
    if args.repository_cache:
        options.append('--repository_cache=' + str(args.repository_cache.resolve()))
    worker_options = ['--worker_sandboxing', '--experimental_worker_cancellation']
    deadline = time.monotonic() + args.timeout
    phases = []; result = dict(revision=revision, bazelVersion=environment['USE_BAZEL_VERSION'], host=list(platform.uname()))

    def run(name, arguments, worker=False):
        command = startup + arguments + options + (worker_options if worker else [])
        start = time.monotonic()
        with (root / (name + '.log')).open('w') as output:
            process = subprocess.Popen(command, cwd=consumer, env=environment, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                process.wait(timeout=min(300, max(1, deadline-start)))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
                raise
        phases.append(dict(name=name, command=command, exitCode=process.returncode, wallSeconds=time.monotonic()-start))
        (root / 'phases.json').write_text(json.dumps(phases, indent=2))
        assert process.returncode == 0, (name, root / (name + '.log'))
        return (root / (name + '.log')).read_text()

    def app(name, kind, expected_output):
        execution = root / (name + '-execution.json')
        output = run(name, ['run', '//:' + kind + '_app', '--execution_log_json_file=' + str(execution)], kind == 'worker')
        assert output.rstrip().splitlines()[-1] == expected_output, output
        actions = [r for r in records(execution) if r.get('mnemonic') == 'MSBuildGraph']
        assert len(actions) == 1 and not actions[0].get('cacheHit'), actions
        assert (actions[0].get('runner') == 'worker') == (kind == 'worker'), actions
        report = consumer / 'bazel-bin' / (kind + '_graph.graph/report.json')
        data = json.loads(report.read_text()); assert ('worker' in data) == (kind == 'worker'), data
        (root / (name + '-report.json')).write_text(json.dumps(data, indent=2))
        inventory = products(report.parent / 'workspace')
        (root / (name + '-products.json')).write_text(json.dumps(inventory, indent=2))
        return inventory

    observed = {}; client = None
    try:
        run('sync', ['run', '//:sync'])
        with build.open('a') as output:
            output.write('''\nload(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="worker_graph", macos_worker=True, linux_worker=False, linux_stable_paths=False, profile_build=True)
app_graph(name="local_graph", linux_worker=False, linux_stable_paths=False, profile_build=True)
msbuild_graph_binary(name="worker_app", graph=":worker_graph", project="P2/P2.csproj")
msbuild_graph_binary(name="local_app", graph=":local_graph", project="P2/P2.csproj")
''')
        # Confirm actual worker execution; merely passing --strategy is insufficient.
        cold = app('cold-worker', 'worker', '1'); local = app('cold-local', 'local', '1')
        assert cold == local, 'Cold local/worker byte or mode parity failed'
        source = consumer / 'P0/Code.cs'; source.write_text(source.read_text().replace('=> 1', '=> 2'))
        body = app('body-worker', 'worker', '2'); local = app('body-local', 'local', '2')
        assert body == local, 'Body local/worker byte or mode parity failed'
        assert body['P0/bin/Release/net11.0/P0.dll'] != cold['P0/bin/Release/net11.0/P0.dll']
        assert body['P0/obj/Release/net11.0/ref/P0.dll'] == cold['P0/obj/Release/net11.0/ref/P0.dll']
        original = source.read_text(); source.write_text(original + '\n// issue224-cancel\n')
        command = startup + ['build', '//:worker_graph'] + options + worker_options
        start = time.monotonic()
        with (root / 'cancel.log').open('w') as output:
            client = subprocess.Popen(command, cwd=consumer, env=environment, stdout=output,
                                      stderr=subprocess.STDOUT, start_new_session=True)
            ready_deadline = min(deadline, time.monotonic() + 120)
            broker = None
            while broker is None:
                assert client.poll() is None, 'Cancellation build ended before delay was active'
                assert time.monotonic() < ready_deadline, 'Owned delay readiness timed out'
                rows = processes()
                for pid, (_, command_line) in rows.items():
                    if marker not in command_line:
                        continue
                    ancestor = pid
                    while ancestor in rows:
                        parent, arguments = rows[ancestor]
                        if 'GraphBuild.dll' in arguments and 'worker ' in arguments and '--persistent_worker' in arguments:
                            assert str(base) + '/' in arguments, arguments
                            broker = ancestor
                            # Include actual delay descendants, not just the shell marker.
                            descendants = {pid}
                            while added := {p for p, (q, _) in rows.items() if q in descendants} - descendants:
                                descendants.update(added)
                            if not any(rows[p][1].split() in (['/bin/sleep', '600'], ['sleep', '600']) for p in descendants):
                                broker = None; break
                            observed = {p: (rows[p][1], identity(p)) for p in descendants}
                            break
                        ancestor = parent
                    if broker is not None:
                        break
                time.sleep(.05)
            broker_started = identity(broker); cancelled = time.monotonic()
            os.killpg(client.pid, signal.SIGINT)  # includes a possible Bazelisk/shell launcher
            code = client.wait(timeout=min(30, max(1, deadline-time.monotonic())))
            assert code != 0, code
            stop = min(deadline, time.monotonic() + 15)
            while set(observed) & processes().keys() and time.monotonic() < stop:
                time.sleep(.05)
            assert not set(observed) & processes().keys(), 'Cancelled owned descendants survived'
            assert not (consumer / 'bazel-bin/worker_graph.graph/report.json').exists(), 'Cancelled output published'
            assert broker in processes(), 'Broker did not survive cooperative cancellation'
            result['cancellation'] = dict(clientExit=code, brokerPid=broker, brokerStart=broker_started,
                ownedPids=list(observed), readySeconds=cancelled-start, cancellationSeconds=time.monotonic()-cancelled)
        source.write_text(original.replace('=> 2', '=> 3'))
        app('next-worker', 'worker', '3')
        assert broker in processes() and identity(broker) == broker_started, 'Next request did not retain the broker'
        result.update(passed=True, parityFiles=len(body), nextBrokerSurvived=True)
    except BaseException as error:
        result.update(passed=False, error=repr(error))
        raise
    finally:
        if client is not None and client.poll() is None:
            os.killpg(client.pid, signal.SIGKILL); client.wait(timeout=10)
        # Only verified fixture descendants can be stopped on a failed control.
        rows = processes()
        for pid, (arguments, started) in reversed(list(observed.items())):
            if pid in rows and rows[pid][1] == arguments and identity(pid) == started:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            with (root / 'shutdown.log').open('w') as output:
                shutdown = subprocess.run(startup + ['shutdown'], cwd=consumer, env=environment,
                    stdout=output, stderr=subprocess.STDOUT, timeout=30)
            result['shutdownExit'] = shutdown.returncode
            assert shutdown.returncode == 0, 'Owned Bazel shutdown failed'
        finally:
            (root / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
