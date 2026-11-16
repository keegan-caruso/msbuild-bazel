#!/usr/bin/env python3
"""Qualify quickstart whole-action recovery on Linux x64 with a local HTTP cache.

The HTTP service remains up between phases. The producer is the first Bazel
server/action process; it is stopped before the fresh read-only consumer starts.
No project-snapshot recovery, worker-default or cross-host claim is made.
"""
import argparse
import collections
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import threading
import urllib.parse


class Cache(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, root, limit):
        super().__init__(('127.0.0.1', 0), Handler)
        self.root, self.limit, self.used, self.reserved = root, limit, 0, 0
        self.phase = 'seed'
        self.counts = collections.Counter()
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def reply(self, code, size=0):
        self.send_response(code)
        self.send_header('Content-Length', str(size))
        self.end_headers()

    def key(self):
        path = urllib.parse.urlsplit(self.path).path
        if not re.fullmatch(r'/(?:ac|cas|rules-msbuild/ac)/[0-9a-f]{64}', path):
            return None
        return self.server.root / path.lstrip('/')

    def record(self, method, status):
        with self.server.lock:
            self.server.counts[(self.server.phase, method, status)] += 1

    def do_GET(self):
        path = self.key()
        if path is None or not path.is_file():
            self.record('GET', 404); self.reply(404); return
        self.record('GET', 200)
        self.reply(200, path.stat().st_size)
        with path.open('rb') as f:
            shutil.copyfileobj(f, self.wfile, 1024 * 1024)

    def do_HEAD(self):
        path = self.key()
        status = 200 if path is not None and path.is_file() else 404
        self.record('HEAD', status)
        self.reply(status, path.stat().st_size if status == 200 else 0)

    def do_PUT(self):
        path = self.key()
        with self.server.lock:
            readonly = self.server.phase != 'seed'
        if readonly or path is None:
            self.record('PUT', 403 if readonly else 400)
            self.close_connection = True
            self.reply(403 if readonly else 400)
            return
        size = int(self.headers.get('Content-Length', '-1'))
        if size < 0 or size > 128 * 1024**2:
            status = 411 if size < 0 else 413
            self.record('PUT', status); self.close_connection = True; self.reply(status); return
        with self.server.lock:
            if self.server.used + self.server.reserved + size > self.server.limit:
                allowed = False
            else:
                self.server.reserved += size
                allowed = True
        if not allowed:
            self.record('PUT', 507); self.close_connection = True; self.reply(507); return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + str(threading.get_ident()) + '.tmp')
        try:
            remaining = size
            digest = hashlib.sha256()
            with temporary.open('wb') as out:
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise IOError('incomplete upload')
                    out.write(block); digest.update(block); remaining -= len(block)
            if self.path.startswith('/cas/') and digest.hexdigest() != path.name:
                self.record('PUT', 400); self.reply(400); return
            with self.server.lock:
                old = path.stat().st_size if path.exists() else 0
                os.replace(temporary, path)
                self.server.used += size - old
            self.record('PUT', 200); self.reply(200)
        finally:
            with self.server.lock:
                self.server.reserved -= size
            temporary.unlink(missing_ok=True)


def rows(path):
    data, result, decoder = path.read_text(), [], json.JSONDecoder()
    while data.strip():
        data = data.lstrip()
        item, size = decoder.raw_decode(data)
        result.append(item)
        data = data[size:]
    return result


def tree(root):
    result = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(current) / name
            relative = str(path.relative_to(root))
            info = path.lstat()
            if path.is_symlink():
                result[relative] = {'link': os.readlink(path)}
            elif path.is_file():
                h = hashlib.sha256()
                with path.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        h.update(chunk)
                result[relative] = {'sha256': h.hexdigest(), 'mode': info.st_mode & 0o777}
            elif path.is_dir():
                result[relative] = {'directory': True, 'mode': info.st_mode & 0o777}
            else:
                raise ValueError('Unexpected graph output: ' + relative)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new disposable directory with evidence and cache')
    parser.add_argument('--rules', type=Path, required=True, help='reviewed checkout containing quickstart')
    parser.add_argument('--bazel', type=Path, required=True, help='explicit Bazel launcher')
    parser.add_argument('--repository-cache', type=Path, help='existing or new Bazel repository download cache')
    parser.add_argument('--expected-revision', required=True, help='full reviewed rules commit ID')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        parser.error('This control requires native Linux x86_64')
    rules, bazel, folder = args.rules.resolve(), args.bazel.resolve(), args.directory.resolve()
    if not bazel.is_file():
        parser.error('Specify an existing launcher')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=rules, text=True).strip()
    if revision != args.expected_revision or not re.fullmatch(r'[0-9a-f]{40}', revision):
        parser.error('rules checkout does not match the full expected revision')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=rules, text=True).strip():
        parser.error('rules checkout must be clean')
    folder.mkdir(parents=True, exist_ok=False)
    cache_dir = folder / 'http-cache'; cache_dir.mkdir()
    workspace = folder / 'quickstart'
    shutil.copytree(rules / 'examples/quickstart', workspace)
    module = workspace / 'MODULE.bazel'
    text = module.read_text()
    text, count = re.subn(r'(local_path_override\(\s*module_name\s*=\s*"rules_msbuild",\s*path\s*=\s*)"[^"]+"',
                          lambda m: m.group(1) + json.dumps(str(rules)), text, count=1)
    if count != 1:
        raise ValueError('Quickstart rules override not found')
    module.write_text(text)
    global_json = json.loads((workspace / 'global.json').read_text())
    if global_json['sdk']['version'] != '11.0.100':
        raise ValueError('Expected reviewed SDK 11.0.100 quickstart')
    server = Cache(cache_dir, 1024**3)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.2',
                       RULES_MSBUILD_PROJECT_CACHE_URL=url, RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='1')
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    snapshots = {}
    pins = json.loads((rules / 'scripts/toolchains.json').read_text())
    if pins['dotnet']['version'] != '11.0.100':
        raise ValueError('Rules checkout SDK pin differs from quickstart')
    report = {'rulesRevision': revision, 'sdk': '11.0.100',
              'sdkArchiveSha256': pins['dotnet']['sha256'], 'bazel': '9.3.2', 'phases': {}}
    try:
        version = subprocess.run([str(bazel), '--version'], cwd=workspace, env=environment,
                                 capture_output=True, text=True, timeout=120)
        if version.returncode or '9.3.2' not in version.stdout + version.stderr:
            raise RuntimeError('Expected Bazel 9.3.2: ' + version.stdout + version.stderr)
        sync_base = [str(bazel), '--ignore_all_rc_files', '--host_jvm_args=-Xmx1024m',
                     '--output_base=' + str(folder / 'sync-base')]
        sync_flags = ['--jobs=2', '--local_test_jobs=1', '--disk_cache=', '--remote_cache=']
        if args.repository_cache:
            sync_flags.append('--repository_cache=' + str(args.repository_cache.resolve()))
        try:
            sync = subprocess.run(sync_base + ['run', '//:sync'] + sync_flags + ['--', '--check'],
                                  cwd=workspace, env=environment, capture_output=True, text=True, timeout=900)
            (folder / 'sync.log').write_text(sync.stdout + sync.stderr)
            if sync.returncode:
                raise RuntimeError('Public sync --check failed; see sync.log')
        finally:
            stopped = subprocess.run(sync_base + ['shutdown'], cwd=workspace, env=environment,
                                     capture_output=True, text=True, timeout=60)
            (folder / 'sync-shutdown.log').write_text(stopped.stdout + stopped.stderr)
            if stopped.returncode:
                raise RuntimeError('Could not stop sync Bazel server')
        for phase in ('seed', 'consumer'):
            with server.lock:
                server.phase = phase
            base = [str(bazel), '--ignore_all_rc_files', '--host_jvm_args=-Xmx1024m',
                    '--output_base=' + str(folder / (phase + '-base'))]
            flags = ['--jobs=2', '--local_test_jobs=1', '--worker_max_instances=MSBuildGraph=1',
                     '--disk_cache=', '--remote_cache=' + url, '--remote_max_connections=8',
                     '--remote_timeout=60s', '--remote_cache_async=false', '--remote_download_outputs=all',
                     '--remote_upload_local_results=' + ('true' if phase == 'seed' else 'false'),
                     '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + url,
                     '--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1']
            if args.repository_cache:
                flags.append('--repository_cache=' + str(args.repository_cache.resolve()))
            phase_rows = []
            try:
                for case, command, target in [('test', 'test', '//:tests'), ('app', 'run', '//:app')]:
                    execution = folder / (phase + '-' + case + '.execution.json')
                    cmd = base + [command, target] + flags + ['--execution_log_json_file=' + str(execution)]
                    if command == 'test':
                        cmd += ['--test_output=all'] + (['--nocache_test_results'] if phase == 'consumer' else [])
                    result = subprocess.run(cmd, cwd=workspace, env=environment, capture_output=True, text=True, timeout=900)
                    output = result.stdout + result.stderr
                    (folder / (phase + '-' + case + '.log')).write_text(output)
                    if result.returncode or 'WARNING: Remote Cache:' in output:
                        raise RuntimeError(phase + ' ' + case + ' failed or cache warned; see log')
                    if case == 'test' and 'Executed 1 out of 1 test' not in output:
                        raise AssertionError(phase + ' test did not execute')
                    if case == 'app' and 'Hello from MSBuild and Bazel' not in output:
                        raise AssertionError(phase + ' app did not run')
                    phase_rows.extend(rows(execution))
                graph = [r for r in phase_rows if r.get('mnemonic') == 'MSBuildGraph']
                tests = [r for r in phase_rows if r.get('mnemonic') == 'TestRunner' and
                         r.get('commandArgs') and r['commandArgs'][0].endswith('/test-setup.sh')]
                if not graph or any(bool(r.get('cacheHit')) != (phase == 'consumer') for r in graph):
                    raise AssertionError(phase + ' unexpected graph action cache status: ' + repr(graph))
                if not tests or any(r.get('cacheHit') for r in tests):
                    raise AssertionError(phase + ' test did not execute: ' + repr(tests))
                graph_tree = workspace / 'bazel-bin/graph.graph'
                if not graph_tree.is_dir():
                    raise AssertionError('Graph output tree missing')
                snapshots[phase] = tree(graph_tree)
                (folder / (phase + '-tree.json')).write_text(json.dumps(snapshots[phase], indent=2, sort_keys=True) + '\n')
                report['phases'][phase] = {'graphActions': len(graph), 'graphHits': sum(bool(x.get('cacheHit')) for x in graph),
                                           'executedTests': len(tests), 'treeEntries': len(snapshots[phase])}
            finally:
                stopped = subprocess.run(base + ['shutdown'], cwd=workspace, env=environment, capture_output=True, text=True, timeout=60)
                (folder / (phase + '-shutdown.log')).write_text(stopped.stdout + stopped.stderr)
                if stopped.returncode:
                    raise RuntimeError('Could not stop owned Bazel server')
            # The cache server continues to serve the next phase, but this Bazel
            # producer process and its output base are no longer running.
        if snapshots['seed'] != snapshots['consumer']:
            raise AssertionError('Recovered graph files or modes differ')
        with server.lock:
            counts = {'|'.join(map(str, k)): v for k, v in sorted(server.counts.items())}
            report['httpRequests'] = counts
            report['cacheBytes'] = server.used
            if any(k[0] == 'consumer' and k[1] == 'PUT' for k in server.counts):
                raise AssertionError('Read-only consumer attempted an HTTP PUT')
            if not any(k[0] == 'seed' and k[1] == 'PUT' and k[2] == 200 for k in server.counts):
                raise AssertionError('Seed did not publish to the HTTP cache')
        report['outputTreesMatch'] = True
        (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('PASS: x64 quickstart seed stopped; fresh read-only consumer recovered graph and ran tests')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=10)
        # Persist counts even on failure for diagnosis.
        with server.lock:
            counts = {'|'.join(map(str, k)): v for k, v in sorted(server.counts.items())}
        (folder / 'http-counts.json').write_text(json.dumps(counts, indent=2) + '\n')


if __name__ == '__main__':
    main()
