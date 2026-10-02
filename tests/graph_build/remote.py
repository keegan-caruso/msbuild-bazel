"""Fault-injection controls for generic graph snapshot transport."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
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
    unavailable = False
    transient = 2
    retries = 0
    active = 0
    peak = 0
    gets = {}
    truncate = None
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def handle_request(self, upload):
        if self.headers.get('Authorization') != 'Bearer fixture-token':
            self.send_error(401)
            return
        with self.lock:
            if Cache.unavailable:
                self.send_error(503)
                return
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
            if not upload:
                with self.lock:
                    Cache.gets[self.path] = Cache.gets.get(self.path, 0) + 1
            data = self.blobs.get(self.path)
            if data is None:
                self.send_error(404)
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(0 if upload else len(data)))
                self.end_headers()
                if not upload and self.path == Cache.truncate:
                    self.wfile.write(data[:len(data) // 2])
                    self.close_connection = True
                else:
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

            def outputs():
                return {str(p.relative_to(root)): p.read_bytes() for project in contract['Projects'].values()
                        for directory in project['OutputDirectories'] for p in (root / directory).rglob('*')
                        if p.is_file() and p.suffix in ['.dll', '.pdb']}

            seed = build()
            original_outputs = outputs()
            assert seed['hits'] == 0
            assert seed['remote']['uploadBytes'] > 0 and seed['remote']['uploads'] > 0, seed
            assert Cache.retries == 2
            snapshots = [json.loads(path.read_text()) for path in cache.glob("*/manifest.json")]
            payloads = {digest for snapshot in snapshots for digest in snapshot["Files"].values()}
            unshared_downloads = sum(len(set(snapshot["Files"].values())) for snapshot in snapshots)
            Cache.gets = {}
            replay = build()
            assert replay['hits'] == 3
            assert replay['remote']['downloadBytes'] > 0 and replay['remote']['downloads'] > 0, replay
            assert replay['remote']['uploadBytes'] == 0, replay
            assert all(Cache.gets.get('/cas/' + digest) == 1 for digest in payloads), Cache.gets
            print(f"Payload downloads: {len(payloads)} distinct versus {unshared_downloads} per-snapshot requests; "
                  f"reported transfer: {replay['remote']['downloadBytes']} bytes including manifests")
            assert Cache.peak > 1
            assert outputs() == original_outputs
            # A missing snapshot is an ordinary miss; rebuilding repairs its pointer.
            action = next(key for key in Cache.blobs if '/ac/' in key)
            pointer = Cache.blobs.pop(action)
            assert build()['misses'] == 1
            assert Cache.blobs[action] == pointer and outputs() == original_outputs
            assert build()['hits'] == 3 and outputs() == original_outputs
            print('PASS: missing snapshot rebuild and exact restoration')
            # Valid transport hashes do not make invalid snapshot metadata safe.
            saved = dict(Cache.blobs)
            metadata = json.loads(pointer)
            manifest_digest = metadata['outputFiles'][0]['digest']['hash']
            snapshot = json.loads(Cache.blobs['/cas/' + manifest_digest])
            snapshot['Fingerprint'] = 'wrong-fingerprint'
            corrupt = json.dumps(snapshot).encode()
            corrupt_digest = hashlib.sha256(corrupt).hexdigest()
            Cache.blobs['/cas/' + corrupt_digest] = corrupt
            metadata['outputFiles'][0]['digest'] = {'hash': corrupt_digest, 'sizeBytes': str(len(corrupt))}
            Cache.blobs[action] = json.dumps(metadata).encode()
            assert 'Project-cache fingerprint mismatch' in build(success=False)
            assert not list(cache.glob('*.fetch-*'))
            Cache.blobs = saved
            assert build()['hits'] == 3 and outputs() == original_outputs
            print('PASS: corrupt snapshot rejection and exact recovery')
            # Unavailability exhausts bounded retries and must fail explicitly.
            Cache.unavailable = True
            failure = build(success=False)
            assert '503' in failure, failure
            assert not list(cache.glob('*.fetch-*'))
            Cache.unavailable = False
            assert build()['hits'] == 3 and outputs() == original_outputs
            print('PASS: unavailable service explicit failure and exact recovery')
            # Eviction must become a miss and a successful rebuild must repair it.
            missing = next(key for key, value in Cache.blobs.items() if key.startswith('/cas/') and value[:2] == b'MZ')
            del Cache.blobs[missing]
            assert build()['misses'] >= 1
            assert missing in Cache.blobs
            assert build()['hits'] == 3 and outputs() == original_outputs
            print('PASS: missing artifact rebuild and exact recovery')
            # A truncated transfer never publishes a partial snapshot.
            Cache.truncate = missing
            build(success=False)
            assert not list(cache.glob('*.fetch-*'))
            assert not list((cache / '.cas').glob('*.pending-*'))
            Cache.truncate = None
            assert build()['hits'] == 3
            # Corruption is rejected rather than mistaken for an ordinary miss.
            original_blob = Cache.blobs[missing]
            Cache.blobs[missing] = b'corrupt'
            assert 'Corrupt project-cache blob' in build(success=False)
            assert not list(cache.glob('*.fetch-*'))
            Cache.blobs[missing] = original_blob
            assert build()['hits'] == 3 and outputs() == original_outputs
            print('PASS: corrupt artifact rejection and exact recovery')
            print(f'PASS: auth, {Cache.retries} transient retries, parallel transfers, one download per distinct payload, CAS eviction repair, interrupted transfer cleanup, corruption rejection')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
