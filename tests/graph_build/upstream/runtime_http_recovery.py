"""Seed native source-runtime actions, stop the producer, and recover read-only.

Use a prepared input-only workspace and a clean pinned rules checkout. This
same-host Linux x64 control does not qualify physical cross-host recovery.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from linux_action_recovery import Cache, Handler, rows, tree


class RecoveryHandler(Handler):
    def guard(self):
        path = self.key()
        if self.server.phase == 'recover' and (path is None or not path.is_file()):
            with self.server.lock:
                self.server.misses.append(self.path)
                active = self.server.active
            if active is not None:
                try:
                    os.killpg(active.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        return path

    def do_HEAD(self):
        self.guard()
        super().do_HEAD()

    def do_GET(self):
        path = self.guard()
        if path is None or not path.is_file():
            self.record('GET', 404)
            self.reply(404)
            return
        self.record('GET', 200)
        self.reply(200, path.stat().st_size)
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                self.wfile.write(chunk)
                with self.server.lock:
                    self.server.get_bytes[self.server.phase] += len(chunk)


def convenience_links(workspace):
    names = {'bazel-bin', 'bazel-out', 'bazel-testlogs', 'bazel-' + workspace.name}
    return {name for name in names if (workspace / name).is_symlink()}


def inputs(workspace):
    ignored = convenience_links(workspace)
    result = {name: value for name, value in tree(workspace).items()
              if Path(name).parts[0] not in ignored}
    for name, value in result.items():
        if 'link' in value or set(Path(name).parts) & {'bin', 'obj', '.nuget', '.graph-tools'}:
            raise ValueError('Workspace contains links or outputs: ' + name)
    return result


def copy_inputs(source, target, manifest):
    ignored = convenience_links(source)
    shutil.copytree(source, target, ignore=lambda directory, names:
                    ignored if Path(directory) == source else [])
    if inputs(target) != manifest:
        raise ValueError('Input closure changed during copying')


def product(workspace):
    with (workspace / 'bazel-bin/runtime_package.tar.gz').open('rb') as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    files = tree(workspace / 'bazel-bin/app_source_runtime.layout')
    count = sum('sha256' in value for value in files.values())
    if count <= 100:
        raise ValueError('Expected complete runtime layout')
    return dict(archiveSha256=digest.hexdigest(), fileCount=count, files=files)


def validate_recovery(logged, cold, producer, consumer):
    local = [row for row in logged if not row.get('cacheHit') or row.get('runner') != 'remote cache hit']
    if len(local) != 1 or local[0].get('mnemonic') != 'MSBuildNativeToolchainPackages' or \
            local[0].get('targetLabel') != '//native:tools' or local[0].get('runner') != 'processwrapper-sandbox':
        raise ValueError('Unexpected local recovery spawn: ' + repr(local))
    originals = [row for row in cold if row.get('mnemonic') == 'MSBuildNativeToolchainPackages' and
                 row.get('targetLabel') == '//native:tools']
    if len(originals) != 1 or not local[0].get('actualOutputs') or \
            sorted(local[0]['actualOutputs'], key=lambda row: row['path']) != \
            sorted(originals[0].get('actualOutputs', []), key=lambda row: row['path']):
        raise ValueError('Local package preparation output digests differ')
    expected = tree(producer / 'bazel-bin/native/tools.root')
    actual = tree(consumer / 'bazel-bin/native/tools.root')
    if not expected or actual != expected:
        raise ValueError('Local package preparation bytes, modes or links differ')
    for mnemonic, count in [('RuntimeNative', 3), ('MSBuildGraph', 3),
                            ('MSBuildGraphRestore', 1), ('RuntimeNativeVersions', 1)]:
        matches = [row for row in logged if row.get('mnemonic') == mnemonic]
        if len(matches) != count or not all(row.get('cacheHit') for row in matches):
            raise ValueError('Expected remote producer recovery: ' + mnemonic)
    return dict(remoteHits=len(logged)-1, localPreparation=dict(
        mnemonic='MSBuildNativeToolchainPackages', targetLabel='//native:tools',
        reason='Declared no-remote because dpkg-deb is host-provided',
        treeEntries=len(actual), treeSha256=hashlib.sha256(
            json.dumps(actual, sort_keys=True).encode()).hexdigest(), matchesColdBytesModesLinks=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('directory', type=Path, help='fresh disposable directory (45 GiB free)')
    parser.add_argument('--rules', required=True, type=Path)
    parser.add_argument('--expected-revision', required=True)
    parser.add_argument('--bazel', required=True, type=Path)
    parser.add_argument('--repository-cache', type=Path)
    parser.add_argument('--distdir', type=Path)
    parser.add_argument('--phase-timeout', type=int, default=9000)
    args = parser.parse_args()
    source, folder, rules, bazel = (p.resolve() for p in
                                   [args.workspace, args.directory, args.rules, args.bazel])
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        parser.error('requires native Linux x64')
    if not source.is_dir() or not bazel.is_file() or folder.exists() or folder.is_relative_to(source):
        parser.error('require existing workspace/launcher and fresh independent directory')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=rules, text=True).strip()
    if len(revision) != 40 or revision != args.expected_revision:
        parser.error('rules must match the full expected revision')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=rules, text=True).strip():
        parser.error('rules checkout must be clean')
    folder.mkdir(parents=True)
    if shutil.disk_usage(folder).free < 45 * 1024**3:
        parser.error('at least 45 GiB free is required')
    manifest = inputs(source)
    (folder / 'input-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    # Copy both from the audited inputs before any producer build can modify them.
    producer, consumer = folder / 'producer', folder / 'consumer'
    for workspace in [producer, consumer]:
        copy_inputs(source, workspace, manifest)
    cache = folder / 'http-cache'
    cache.mkdir()
    server = Cache(cache, 20 * 1024**3, 1024**3)
    server.RequestHandlerClass = RecoveryHandler
    server.get_bytes, server.misses, server.active = collections.Counter(), [], None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.3', DOTNET_CLI_USE_MSBUILD_SERVER='false',
                       MSBUILDUSESERVER='0', RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='1')
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    version = subprocess.run([str(bazel), '--version'], cwd=source, env=environment, capture_output=True, text=True, timeout=120)
    if version.returncode or version.stdout.strip() != 'bazel 9.3.3':
        server.shutdown()
        raise ValueError('Expected Bazel 9.3.3: ' + version.stdout + version.stderr)
    report = dict(scope='same-host native Linux x64', rulesRevision=revision, bazel='9.3.3',
                  source=str(source), phases={}, inputFileCount=sum('sha256' in v for v in manifest.values()))

    def save():
        with server.lock:
            report.update(http={str(k): v for k, v in server.counts.items()},
                          getPayloadBytes=dict(server.get_bytes), recoverMisses=list(server.misses))
        temporary = folder / 'report.json.tmp'
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(folder / 'report.json')

    def invoke(name, workspace, base, action, targets, extra):
        log = folder / (name + '.execution.json')
        command = [str(bazel), '--batch', '--host_jvm_args=-Xmx1024m', '--output_base=' + str(base),
                   '--output_user_root=' + str(base) + '-user', '--ignore_all_rc_files', action, *targets,
                   '--override_module=rules_msbuild=' + str(rules), '--jobs=1', '--strategy=MSBuildGraph=worker',
                   '--worker_sandboxing', '--disk_cache=', '--remote_cache=' + url, '--remote_cache_async=false',
                   '--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1', '--execution_log_json_file=' + str(log), *extra]
        if args.repository_cache:
            command.append('--repository_cache=' + str(args.repository_cache.resolve()))
        if args.distdir:
            command.append('--distdir=' + str(args.distdir.resolve()))
        started = time.monotonic()
        save()
        with (folder / (name + '.log')).open('w') as output:
            process = subprocess.Popen(command, cwd=workspace, env=environment, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            with server.lock:
                server.active = process
            try:
                process.wait(timeout=args.phase_timeout)
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=30)
                raise
            finally:
                with server.lock:
                    server.active = None
        phase = dict(command=command, wallSeconds=time.monotonic() - started, exitCode=process.returncode)
        report['phases'][name] = phase
        save()
        if process.returncode:
            raise RuntimeError('Bazel failed: ' + name)
        logged = rows(log)
        phase['spawns'] = [{key: row.get(key) for key in ['mnemonic', 'cacheHit', 'runner', 'targetLabel']}
                           for row in logged]
        save()
        return logged

    try:
        seeded = invoke('seed', producer, folder / 'seed-base', 'test',
                        ['//:app_test', '//:runtime_test', '//:runtime_package'],
                        ['--noremote_accept_cached', '--nocache_test_results', '--test_output=all'])
        for mnemonic in ['RuntimeNative', 'MSBuildGraph']:
            if not any(r.get('mnemonic') == mnemonic and not r.get('cacheHit') for r in seeded):
                raise ValueError('No executed producer: ' + mnemonic)
        expected = product(producer)
        report['producer'] = expected
        # --batch exits the producer server and workers before returning.
        if (folder / 'seed-base/server/server.pid.txt').exists() or inputs(producer) != manifest:
            raise ValueError('Producer is running or modified its inputs')
        inventory = tree(cache)
        server.phase = 'recover'
        recovered = invoke('recover', consumer, folder / 'consumer-base', 'build', ['//:app', '//:runtime_package'],
                           ['--remote_upload_local_results=false', '--remote_download_outputs=all'])
        if server.misses:
            raise ValueError('Recovery cache miss: ' + repr(server.misses))
        report['recoveryActions'] = validate_recovery(recovered, seeded, producer, consumer)
        if product(consumer) != expected or inputs(consumer) != manifest:
            raise ValueError('Recovered output or input parity differs')
        server.phase = 'forced-tests'
        tested = invoke('forced-tests', consumer, folder / 'consumer-base', 'test', ['//:app_test', '//:runtime_test'],
                        ['--remote_upload_local_results=false', '--nocache_test_results', '--test_output=all',
                         '--remote_download_outputs=all'])
        shells = [r for r in tested if r.get('mnemonic') == 'TestRunner' and not r.get('cacheHit') and
                  r.get('commandArgs') and r['commandArgs'][0].endswith('/test-setup.sh')]
        if {r.get('targetLabel') for r in shells} != {'//:app_test', '//:runtime_test'}:
            raise ValueError('Both product tests must actually execute')
        local = [r for r in tested if r.get('mnemonic') != 'TestRunner' and not r.get('cacheHit')]
        if local:
            report['forcedPreparation'] = validate_recovery(
                [r for r in recovered if r.get('cacheHit')] + local, seeded, producer, consumer)
        if any(phase != 'seed' and method == 'PUT' and count
               for (phase, method, status), count in server.counts.items()) or tree(cache) != inventory:
            raise ValueError('Read-only consumer modified the cache')
        report['passed'] = True
    except BaseException as error:
        report.update(passed=False, error=repr(error))
        raise
    finally:
        save()
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
