#!/usr/bin/env python3
"""Run one downloaded-SDK cross-host qualification phase in a fresh Linux guest.

Transfer only the seed evidence JSON to an independent consumer guest. The
caller owns stopping the producer and recording the physical hosts/sessions.
"""
import argparse
import collections
import hashlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from linux_action_recovery import rows, tree


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def handle_request(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b';', 1)[0], 16)
                if not size:
                    while True:
                        trailer = self.rfile.readline()
                        if not trailer:
                            raise EOFError('Incomplete chunked trailers')
                        if trailer == b'\r\n':
                            break
                    break
                chunks.append(self.rfile.read(size))
                if self.rfile.read(2) != b'\r\n':
                    raise ValueError('Invalid chunk terminator')
            payload = b''.join(chunks)
            size = len(payload)
        else:
            size = int(self.headers.get('Content-Length', '0'))
            payload = self.rfile.read(size) if size else None
        key = self.command
        with self.server.lock:
            self.server.counts[key] += 1
            self.server.counts[key + 'RequestBytes'] += size
        if key == 'PUT' and self.server.readonly:
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        headers = {name: self.headers[name] for name in ('Content-Type', 'Content-Encoding', 'Accept')
                   if self.headers.get(name) is not None}
        request = urllib.request.Request(self.server.upstream + self.path, data=payload, method=key, headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            self.send_response(response.status)
            for name in ('Content-Type', 'Content-Encoding'):
                if response.headers.get(name) is not None:
                    self.send_header(name, response.headers[name])
            length = response.headers.get('Content-Length')
            if length is not None:
                self.send_header('Content-Length', length)
            else:
                self.send_header('Connection', 'close')
                self.close_connection = True
            self.end_headers()
            transferred = 0
            if key != 'HEAD':
                while block := response.read(64 * 1024):
                    self.wfile.write(block)
                    transferred += len(block)
            with self.server.lock:
                self.server.counts[key + 'ResponseBytes'] += transferred
                self.server.counts[key + str(response.status)] += 1

    do_GET = do_HEAD = do_PUT = handle_request



# MSBuild's AssemblyReference caches contain transient local resolution state;
# GraphCache.CapturedFiles intentionally does not publish them.
PROJECT_OMISSIONS = {
    'workspace/App/obj/Release/net11.0/App.csproj.AssemblyReference.cache',
    'workspace/Tests/obj/Release/net11.0/Tests.csproj.AssemblyReference.cache',
}


def compare_outputs(seed, recovered, project_replay):
    if project_replay:
        if set(seed) - set(recovered) != PROJECT_OMISSIONS or PROJECT_OMISSIONS & set(recovered):
            raise AssertionError('Project replay must omit exactly its two transient AssemblyReference caches')
        expected = {k: v for k, v in seed.items() if k not in PROJECT_OMISSIONS}
    else:
        expected = seed
    if expected != recovered:
        raise AssertionError('Graph output bytes/modes differ')
    return len(expected)


def workload_identity(report, graph):
    # Read-only/cache location are transport controls removed by GraphRunOptions.
    # Preserve every declared graph input digest and actual command argument.
    record = {key: report[key] for key in ('revision', 'nonce', 'inputTree', 'toolchainPins')}
    record.update({key: graph[key] for key in ('commandArgs', 'inputs', 'listedOutputs')})
    record['environment'] = [item for item in graph['environmentVariables']
                             if not item['name'].startswith('RULES_MSBUILD_PROJECT_CACHE_')]
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def seed_workload_identity(seed, report_path):
    if 'workloadSha256' in seed:
        if not re.fullmatch(r'[0-9a-f]{64}', seed['workloadSha256']):
            raise ValueError('Invalid recorded seed workload digest')
        return seed['workloadSha256']
    # Compatibility with the first frozen qualification report. New reports
    # carry the digest and need no execution-log transfer.
    execution = report_path.with_suffix('.execution.json')
    if not execution.is_file():
        execution = report_path.parent / 'execution.json'
    graph = next(r for r in rows(execution) if r.get('mnemonic') == 'MSBuildGraph')
    return workload_identity(seed, graph)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['seed', 'action', 'project'])
    parser.add_argument('output', type=Path)
    parser.add_argument('--rules', type=Path, required=True)
    parser.add_argument('--seed', type=Path, help='frozen seed JSON, required for action/project; current reports are self-contained')
    parser.add_argument('--revision', required=True)
    parser.add_argument('--nonce', required=True)
    parser.add_argument('--acquisition', type=Path, help='download-only mount; no action/project outputs')
    args = parser.parse_args()
    if args.phase != 'seed' and (args.seed is None or not args.seed.is_file()):
        parser.error('--seed is required for action/project and must name an existing report')
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        parser.error('--revision requires a full commit ID')
    if os.uname().sysname != 'Linux' or os.uname().machine != 'aarch64':
        parser.error('Requires Ubuntu ARM64 guest')
    if not Path('/usr/bin/bwrap').is_file():
        parser.error('Requires packaged Bubblewrap at /usr/bin/bwrap for stable paths')
    rules, output = args.rules.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    shutil.copytree(rules / 'examples/quickstart', workspace)
    module = workspace / 'MODULE.bazel'
    module.write_text(module.read_text().replace('path = "../msbuild-bazel"', 'path = ' + json.dumps(str(rules))))
    for relative in ('Library/Message.cs', 'App/Program.cs', 'Tests/Program.cs'):
        source = workspace / relative
        source.write_text(source.read_text() + '\n// Qualification nonce: ' + args.nonce + '\n')
    build = workspace / 'BUILD.bazel'
    build.write_text(build.read_text().replace('app_graph(name = "graph")', 'app_graph(name = "graph", profile_build = True, linux_worker = False, linux_stable_paths = True)'))
    proxy = ThreadingHTTPServer(('127.0.0.1', 18723), Proxy)
    proxy.upstream = os.environ['RULES_MSBUILD_SHARED_CACHE_URL'].rstrip('/')
    proxy.readonly = args.phase != 'seed'
    proxy.counts = collections.Counter()
    proxy.lock = threading.Lock()
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    url = 'http://127.0.0.1:18723'
    env = dict(os.environ, USE_BAZEL_VERSION='9.3.3', RULES_MSBUILD_PROJECT_CACHE_URL=url,
               RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='0' if args.phase == 'seed' else '1')
    # Keep declared action environment identical between seed and consumers;
    # the counting proxy enforces read-only access for both cache protocols.
    base = [str(rules / '.tools/bin/bazelisk'), '--ignore_all_rc_files', '--host_jvm_args=-Xmx1024m',
            '--output_base=' + str(output / 'bazel')]
    flags = ['--jobs=2', '--local_test_jobs=1', '--disk_cache=', '--remote_cache=' + url,
             '--remote_max_connections=4', '--remote_cache_async=false', '--remote_download_outputs=all',
             '--remote_upload_local_results=' + ('true' if args.phase == 'seed' else 'false'),
             '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + url,
             '--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=' + ('1' if args.phase == 'project' else '0')]
    if args.acquisition:
        acquisition = args.acquisition.resolve()
        pins = json.loads((rules / 'scripts/toolchains.json').read_text())['dotnet']['platforms']['linux-arm64']
        archive = acquisition / 'downloads' / pins['sha256']
        digest = hashlib.sha256()
        with archive.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != pins['sha256']:
            raise ValueError('Acquisition archive does not match SDK pin')
        named = archive.with_name(Path(urlsplit(pins['url']).path).name)
        if not named.exists():
            named.symlink_to(archive.name)
        flags += ['--distdir=' + str(archive.parent), '--repository_cache=' + str(acquisition / 'repositories')]
    if args.phase in ('seed', 'project'):
        flags += ['--remote_accept_cached=false']
    report = {'revision': args.revision, 'phase': args.phase, 'nonce': args.nonce, 'platform': os.uname().sysname + '/' + os.uname().machine}
    report['inputTree'] = tree(workspace)
    report['verifierVersion'] = 2
    report['fixtureSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['toolchainPins'] = json.loads((rules / 'scripts/toolchains.json').read_text())
    started = time.monotonic()
    try:
        execution = output / 'execution.json'
        cmd = base + ['test', '//:tests', '//:app'] + flags + ['--nocache_test_results', '--test_output=all',
              '--execution_log_json_file=' + str(execution)]
        report['command'] = cmd
        result = subprocess.run(cmd, cwd=workspace, env=env, capture_output=True, text=True)
        (output / 'build.log').write_text(result.stdout + result.stderr)
        report['seconds'] = time.monotonic() - started
        if result.returncode or 'WARNING: Remote Cache:' in result.stderr:
            raise RuntimeError('Build failed or remote cache warning; see build.log')
        entries = rows(execution)
        graph = [r for r in entries if r.get('mnemonic') == 'MSBuildGraph']
        tests = [r for r in entries if r.get('mnemonic') == 'TestRunner' and r.get('commandArgs') and r['commandArgs'][0].endswith('/test-setup.sh')]
        if len(graph) != 1 or bool(graph[0].get('cacheHit')) != (args.phase == 'action'):
            raise AssertionError('Unexpected graph action recovery')
        report['spawns'] = [{'mnemonic': r.get('mnemonic'), 'cacheHit': bool(r.get('cacheHit')),
                             'runner': r.get('runner')} for r in entries]
        if args.phase == 'action' and any(not r.get('cacheHit') for r in entries
                                           if r.get('mnemonic') != 'TestRunner'):
            raise AssertionError('A build spawn missed the whole-action cache')
        if not tests or any(r.get('cacheHit') for r in tests):
            raise AssertionError('Forced test did not execute')
        graph_root = workspace / 'bazel-bin/graph.graph'
        report['graphReport'] = json.loads((graph_root / 'report.json').read_text())
        report['tree'] = {k: v for k, v in tree(graph_root).items()
                          if k != 'report.json' and not k.endswith('.binlog')}
        report['workloadSha256'] = workload_identity(report, graph[0])
        report['graphActions'] = len(graph)
        report['graphHits'] = sum(bool(r.get('cacheHit')) for r in graph)
        report['executedTests'] = len(tests)
        if args.phase == 'seed' and (report['graphReport']['hits'] != 0 or report['graphReport']['misses'] != 3):
            raise AssertionError('Expected 0 project hits / 3 cold misses')
        if args.phase == 'project' and (report['graphReport']['hits'] != 3 or report['graphReport']['misses'] != 0):
            raise AssertionError('Expected 3 project hits / 0 misses')
        if args.phase == 'project':
            if report['graphReport']['compilerTasks'] != 0 or report['graphReport']['remote']['downloads'] <= 0:
                raise AssertionError('Project recovery did not demonstrate downloads without compilation')
        app_started = time.monotonic()
        app = subprocess.run(base + ['run', '//:app'] + flags, cwd=workspace, env=env, capture_output=True, text=True)
        (output / 'app.log').write_text(app.stdout + app.stderr)
        report['appSeconds'] = time.monotonic() - app_started
        if app.returncode or 'Hello from MSBuild and Bazel' not in app.stdout + app.stderr:
            raise AssertionError('Recovered app did not run')
        if args.phase != 'seed':
            seed = json.loads(args.seed.read_text())
            if any(report[key] != seed[key] for key in ('nonce', 'revision', 'inputTree', 'toolchainPins')):
                raise AssertionError('Seed identity mismatch')
            report['seedWorkloadSha256'] = seed_workload_identity(seed, args.seed)
            report['seedFixtureSha256'] = seed['fixtureSha256']
            if report['workloadSha256'] != report['seedWorkloadSha256']:
                raise AssertionError('Declared graph workload differs from frozen seed')
            report['outputEntriesCompared'] = compare_outputs(seed['tree'], report['tree'], args.phase == 'project')
            report['parityOmissions'] = sorted(PROJECT_OMISSIONS) if args.phase == 'project' else []
            report['outputTreesMatch'] = True
    finally:
        subprocess.run(base + ['shutdown'], cwd=workspace, env=env, capture_output=True, timeout=60, check=True)
        proxy.shutdown()
        report['http'] = dict(proxy.counts)
        (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    if args.phase != 'seed' and proxy.counts['PUT']:
        raise AssertionError('Consumer attempted PUT')
    print('PASS', args.phase, report['seconds'], report['http'])


if __name__ == '__main__':
    main()
