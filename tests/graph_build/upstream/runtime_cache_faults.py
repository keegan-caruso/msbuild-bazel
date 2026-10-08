"""Unscored cache faults in a qualified full runtime consumer.

A local proxy isolates faults from the real cache: it never changes upstream
contents. Missing entries become misses; corruption and persistent 503s must fail.
Stop the worker between every case and recovery so local snapshots cannot hide a
fault. Keep whole-action caches disabled and compare recovered bytes and modes.
"""
import argparse
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize
from runtime_suite_verify import proofs


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    upstream = ''
    fault = None
    selected = None
    injected = 0
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def proxy_request(self, upload):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0'))) if upload else None
        with self.lock:
            fault = Proxy.fault
        if fault == 'unavailable-service':
            with self.lock:
                Proxy.injected += 1
            self.send_error(503)
            return
        request = urllib.request.Request(self.upstream.rstrip('/') + self.path, data=body, method='PUT' if upload else 'GET')
        for key in ['Authorization', 'Accept', 'Content-Type']:
            if self.headers.get(key):
                request.add_header(key, self.headers[key])
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                status, data = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, data = error.code, error.read()
        if not upload and status == 200 and fault:
            snapshot = '/ac/' in self.path
            artifact = '/cas/' in self.path and data[:2] == b'MZ'
            eligible = (snapshot and fault.endswith('snapshot')) or (artifact and fault.endswith('artifact'))
            with self.lock:
                if eligible and self.selected is None:
                    Proxy.selected = self.path
                selected = self.selected == self.path
                if selected:
                    Proxy.injected += 1
            if selected:
                if fault.startswith('missing'):
                    status, data = 404, b'missing qualification entry'
                elif snapshot:
                    # Valid JSON with an invalid snapshot pointer contract.
                    data = b'{"outputFiles":[]}'
                else:
                    data = b'corrupt qualification payload'
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.proxy_request(False)

    def do_PUT(self):
        self.proxy_request(True)


class Server(ThreadingHTTPServer):
    request_queue_size = 64

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'seed', 'results']:
        parser.add_argument(name, type=Path)
    parser.add_argument('--output-base', required=True, type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    seed = json.loads(args.seed.read_text())
    assert seed['slice'] == 'runtime-suites' and seed['misses'] == 481
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [(p, v) for p, declaration in contract['Projects'].items() for v in declaration.get('Configurations') or [declaration]]
    assert sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for _, v in nodes) == 481
    directories = {d for _, v in nodes for d in v['OutputDirectories']}
    files = {f for _, v in nodes for f in v.get('OutputFiles', [])}
    states = {d + '/' + Path(p).name + '.GenerateResource.cache' for p, v in nodes for d in v['OutputDirectories'] if d.startswith('artifacts/obj/')}
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.0')
    Proxy.upstream = environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL')
    server = Server(('0.0.0.0', 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = 'http://127.0.0.1:' + str(server.server_port)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    generated = root / 'graph.generated.bzl'
    original = generated.read_bytes()
    prefix, action = original.decode().split('    msbuild_graph(\n')
    nonce = root / 'fault-request.txt'
    assert not nonce.exists()
    generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["fault-request.txt",', 1))
    rows = []
    def stop(label):
        with (results / (label + '-stop.log')).open('w') as log:
            subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    def capture():
        workspace = root / 'bazel-bin/graph.graph/workspace'
        paths = {workspace / p for p in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        return {str(p.relative_to(workspace)): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), mode=p.stat().st_mode & 0o777)
                for p in paths if p.is_file() and not p.name.endswith('.AssemblyReference.cache')
                and (str(p.relative_to(workspace)) not in states or str(p.relative_to(workspace)) in files)}
    def build(label, fault=None):
        stop(label)
        Proxy.fault, Proxy.selected, Proxy.injected = fault, None, 0
        nonce.write_text(str(uuid.uuid4()))
        events = results / (label + '.bep')
        with (results / (label + '.log')).open('w') as log:
            process = subprocess.run(bazel + ['build', '//:graph', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
                '--worker_max_instances=MSBuildGraph=1', '--spawn_strategy=linux-sandbox', '--disk_cache=', '--remote_cache=', '--noshow_progress',
                '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint, '--build_event_json_file=' + str(events)],
                cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
        succeeds = fault is None or fault.startswith('missing')
        assert (process.returncode == 0) == succeeds, label
        if fault:
            assert Proxy.injected > 0, 'Fault was not exercised'
        row = dict(case=label, exitCode=process.returncode, injected=Proxy.injected, selected=Proxy.selected)
        if succeeds:
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            assert report['hits'] + report['misses'] == 481
            assert report['misses'] == 0 if fault is None else 0 < report['misses'] < 481
            assert capture() == seed['outputs'], 'Fault recovery must reproduce exact producer files/bytes/modes'
            row.update(hits=report['hits'], misses=report['misses'], files=len(seed['outputs']))
        else:
            log = (results / (label + '.log')).read_text()
            expected = {'corrupt-snapshot': 'Unexpected project-cache action result',
                        'corrupt-artifact': 'Corrupt project-cache blob', 'unavailable-service': '503'}[fault]
            assert expected in log, label
            base = args.output_base / 'bazel-workers'
            scratch = Path('/tmp') / ('rules-msbuild-workers-' + str(os.getuid()))
            assert not any(list(folder.rglob(pattern)) for folder in [base, scratch] for pattern in ['*.fetch-*', '*.pending-*']), 'Partial cache entry survived'
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
    def verify_suites():
        with (results / 'restored-service-tests.log').open('w') as log:
            subprocess.run(bazel + ['test', '//:runtime_suites', '--jobs=1', '--local_test_jobs=1',
                '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
                '--strategy=RuntimeNative=standalone', '--spawn_strategy=linux-sandbox', '--disk_cache=', '--remote_cache=', '--test_output=errors',
                '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint, '--noshow_progress'],
                cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        suite = json.loads((root / 'suite.json').read_text())
        application = json.loads((root / 'application.json').read_text())
        assert len(suite['tests']) == 8
        expected = {}
        for scope in ['managed', 'private']:
            for name, producer in application.get(scope, {}).items():
                expected.setdefault(name, set()).add(hashlib.sha256((root / 'bazel-bin/graph.graph/workspace' / producer['path']).read_bytes()).hexdigest().upper())
        for name, producer in application['native'].items():
            expected.setdefault(name, set()).add(hashlib.sha256((root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name).read_bytes()).hexdigest().upper())
        required = {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
        signatures, observations = {}, 0
        for selection in suite['tests']:
            logs = root / 'bazel-testlogs' / selection['target'].removeprefix('//:')
            cases = Counter((c.get('name'), 'failed' if c.find('failure') is not None or c.find('error') is not None
                else 'skipped' if c.find('skipped') is not None else 'passed') for c in ET.parse(logs / 'test.xml').getroot().findall('.//testcase'))
            canonical = sorted((name, outcome, count) for (name, outcome), count in normalize(cases).items())
            signatures[selection['target']] = dict(cases=sum(cases.values()), sha256=hashlib.sha256(json.dumps(canonical).encode()).hexdigest())
            observed = proofs(logs / 'test.outputs')
            assert observed
            for proof in observed:
                assert required <= proof['files'].keys()
                for name, value in proof['files'].items():
                    if name in expected:
                        assert value['sha256'] in expected[name], name
                        observations += 1
        assert signatures == json.loads((args.seed.parent / 'seed-tests.json').read_text()), 'Recovered real cases/outcomes differ'
        row = dict(case='restored-service-suites', testOutcomes=sum(s['cases'] for s in signatures.values()), sourceHashObservations=observations)
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
    try:
        build('baseline')
        for fault in ['missing-snapshot', 'corrupt-snapshot', 'missing-artifact', 'corrupt-artifact', 'unavailable-service']:
            build(fault, fault)
            build(fault + '-recovered')
        verify_suites()
        print('PASS: five independent runtime cache faults, exact recovered outputs and source-host suites', flush=True)
    finally:
        Proxy.fault = None
        generated.write_bytes(original)
        nonce.unlink(missing_ok=True)
        try:
            stop('final')
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
