"""Fault-injection controls for generic graph snapshot transport."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import sys

from qualify import DOTNET, ENV, RUNNER, fixture, run


class Cache(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    blobs = {}
    transient = 2
    retries = 0
    active = 0
    peak = 0
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def handle_request(self, upload):
        if self.headers.get('Authorization') != 'Bearer fixture-token':
            self.send_error(401)
            return
        with self.lock:
            if Cache.transient:
                Cache.transient -= 1
                Cache.retries += 1
                self.send_error(503)
                return
            Cache.active += 1
            Cache.peak = max(Cache.peak, Cache.active)
        try:
            time.sleep(0.015)
            if upload:
                self.blobs[self.path] = self.rfile.read(int(self.headers['Content-Length']))
            data = self.blobs.get(self.path)
            if data is None:
                self.send_error(404)
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(0 if upload else len(data)))
                self.end_headers()
                self.wfile.write(b'' if upload else data)
        finally:
            with self.lock:
                Cache.active -= 1

    def do_GET(self):
        self.handle_request(False)

    def do_PUT(self):
        self.handle_request(True)


class CacheServer(ThreadingHTTPServer):
    request_queue_size = 64

    def handle_error(self, request, client_address):
        # Parallel transfers are cancelled when a blob is missing or corrupt.
        if not isinstance(sys.exception() if hasattr(sys, 'exception') else sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def main():
    server = CacheServer(('127.0.0.1', 0), Cache)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ENV['RULES_MSBUILD_PROJECT_CACHE_URL'] = f'http://127.0.0.1:{server.server_port}'
    ENV['RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN'] = 'fixture-token'
    ENV['RULES_MSBUILD_GRAPH_PROFILE'] = '1'
    try:
        with tempfile.TemporaryDirectory(prefix='graph-transport-') as temporary:
            work = Path(temporary).resolve()
            root = work / 'workspace'
            root.mkdir()
            contract = fixture(root)
            manifest = work / 'contract.json'
            manifest.write_text(json.dumps(contract))
            report = work / 'report.json'
            cache = work / 'cache'

            def build(success=True):
                shutil.rmtree(cache, ignore_errors=True)
                for project in contract['Projects'].values():
                    for directory in project['OutputDirectories']:
                        shutil.rmtree(root / directory, ignore_errors=True)
                result = run(DOTNET, RUNNER, 'build', root, manifest, report, cache, success=success)
                return json.loads(report.read_text()) if success else result.stderr

            seed = build()
            assert seed['hits'] == 0
            assert seed['remote']['uploadBytes'] > 0 and seed['remote']['uploads'] > 0, seed
            assert Cache.retries == 2
            replay = build()
            assert replay['hits'] == 3
            assert replay['remote']['downloadBytes'] > 0 and replay['remote']['downloads'] > 0, replay
            assert replay['remote']['uploadBytes'] == 0, replay
            assert Cache.peak > 1
            # Eviction must become a miss and a successful rebuild must repair it.
            missing = next(key for key, value in Cache.blobs.items() if key.startswith('/cas/') and value[:2] == b'MZ')
            del Cache.blobs[missing]
            assert build()['misses'] >= 1
            assert missing in Cache.blobs
            assert build()['hits'] == 3
            # Corruption is rejected rather than mistaken for an ordinary miss.
            Cache.blobs[missing] = b'corrupt'
            assert 'Corrupt project-cache blob' in build(success=False)
            assert not list(cache.glob('*.fetch-*'))
            print(f'PASS: auth, {Cache.retries} transient retries, parallel transfers, CAS eviction repair, corruption rejection')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
