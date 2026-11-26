"""Remote misses and broken downloads must not fall back to local producers."""
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import signal
import subprocess
import sys
import threading
import tempfile
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_build'))
from read_only_cache_proxy import ReadOnlyCacheProxy

PAYLOAD = b'cross-host body' * 100
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class Upstream(BaseHTTPRequestHandler):
    puts = 0
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        present = self.path == '/cas/' + DIGEST
        self.send_response(200 if present else 404)
        self.send_header('Content-Length', str(len(PAYLOAD)) if present else '0')
        self.end_headers()
        if present and self.command == 'GET':
            self.wfile.write(PAYLOAD)

    def do_PUT(self):
        type(self).puts += 1
        self.send_response(500)
        self.send_header('Content-Length', '0')
        self.end_headers()


class CacheProxy(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.upstream.daemon_threads = True
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.proxy = ReadOnlyCacheProxy('http://127.0.0.1:' + str(self.upstream.server_port))
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()
        for server in [self.upstream, self.proxy]:
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.proxy.server_port)
        Upstream.puts = 0

    def test_remote_misses_stop_own_bazel_group_before_reply(self):
        for method in ['GET', 'HEAD']:
            with self.subTest(method=method):
                child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
                self.proxy.active = child
                try:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(urllib.request.Request(self.url + '/ac/' + '0' * 64, method=method))
                    self.assertEqual(caught.exception.code, 404)
                    self.assertEqual(child.wait(timeout=3), -signal.SIGTERM)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.wait()
                    self.proxy.active = None
        self.assertEqual(len(self.proxy.misses), 2)

    def test_payload_and_local_write_rejection(self):
        self.assertEqual(urllib.request.urlopen(self.url + '/cas/' + DIGEST).read(), PAYLOAD)
        deadline = time.monotonic() + 3
        while self.proxy.get_bytes['recover'] != len(PAYLOAD) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.proxy.get_bytes['recover'], len(PAYLOAD))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(urllib.request.Request(self.url + '/cas/' + DIGEST, data=b'write', method='PUT'))
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(Upstream.puts, 0)
        self.assertFalse(self.proxy.misses)

    def test_cli_reports_streamed_bytes_for_one_owned_phase(self):
        self.cli_case(present=True, ignore_term=False)

    def test_cli_stops_even_signal_ignoring_requester_before_fallback(self):
        self.cli_case(present=False, ignore_term=True)

    def cli_case(self, present, ignore_term):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / 'fake_bazel.py'
            marker = root / 'fallback'
            fake.write_text("import signal,sys,urllib.request,urllib.error\n" +
                ("signal.signal(signal.SIGTERM,signal.SIG_IGN)\n" if ignore_term else '') +
                "url=next(a.split('=',1)[1] for a in sys.argv if a.startswith('--remote_cache='))\n" +
                "try: data=urllib.request.urlopen(url+'/cas/" + (DIGEST if present else '0'*64) + "').read()\n" +
                "except urllib.error.HTTPError: open(" + repr(str(marker)) + ",'w').write('fallback')\n")
            report = root / 'phase.json'
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'graph_build/read_only_cache_proxy.py'),
                       '--cache=http://127.0.0.1:' + str(self.upstream.server_port), '--report=' + str(report),
                       '--abort-grace=0.1', '--', sys.executable, str(fake), '--batch',
                       '--output_base=' + str(root / 'base'), 'build']
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            receipt = json.loads(report.read_text())
            self.assertEqual(result.returncode, 0 if present else 1, result.stderr)
            self.assertEqual(receipt['passed'], present)
            self.assertFalse(marker.exists(), 'guard returned a cache miss while fallback was possible')
            if present:
                self.assertEqual(receipt['getPayloadBytes']['recover'], len(PAYLOAD))
                self.assertFalse(receipt['misses'])
            else:
                self.assertTrue(receipt['misses'])
                self.assertEqual(receipt['returnCode'], -signal.SIGKILL)

    def test_transport_failure_stops_group(self):
        self.upstream.shutdown()
        self.upstream.server_close()
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        self.proxy.active = child
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.url + '/cas/' + DIGEST)
            self.assertEqual(caught.exception.code, 502)
            self.assertEqual(child.wait(timeout=3), -signal.SIGTERM)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
            self.proxy.active = None
        self.assertTrue(self.proxy.misses)


if __name__ == '__main__':
    unittest.main()
