"""Portable controls for the bounded qualification HTTP cache."""
import hashlib
import http.client
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('linux_action_recovery', ROOT / 'tests/graph_build/linux_action_recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='action-recovery-cache-')
        self.addCleanup(self.temp.cleanup)
        self.cache = recovery.Cache(Path(self.temp.name), 1024)
        self.thread = threading.Thread(target=self.cache.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = 'http://127.0.0.1:' + str(self.cache.server_port)

    def stop(self):
        self.cache.shutdown()
        self.cache.server_close()
        self.thread.join(timeout=10)

    def put(self, path, data):
        request = urllib.request.Request(self.base + path, data=data, method='PUT')
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def test_digest_content_limits_and_read_only_counts(self):
        payload = b'fixture content'
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(self.put('/cas/' + digest, payload), 200)
        with urllib.request.urlopen(self.base + '/cas/' + digest, timeout=5) as response:
            self.assertEqual(response.read(), payload)
        self.assertEqual(self.put('/cas/' + '0' * 64, payload), 400)
        self.assertFalse((Path(self.temp.name) / 'cas' / ('0' * 64)).exists())
        self.assertEqual(self.put('/ac/' + '1' * 64, b'x' * 1025), 507)
        self.cache.phase = 'consumer'
        self.assertEqual(self.put('/cas/' + digest, payload), 403)
        self.assertEqual(self.cache.counts[('consumer', 'PUT', 403)], 1)
        with urllib.request.urlopen(self.base + '/cas/' + digest, timeout=5) as response:
            self.assertEqual(response.read(), payload)
        self.assertEqual(self.cache.counts[('consumer', 'GET', 200)], 1)
        self.assertEqual(self.cache.used, len(payload))

    def test_large_request_is_rejected_before_body(self):
        conn = http.client.HTTPConnection('127.0.0.1', self.cache.server_port, timeout=5)
        self.addCleanup(conn.close)
        conn.putrequest('PUT', '/ac/' + '1' * 64)
        conn.putheader('Content-Length', str(128 * 1024**2 + 1))
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        response.read()


if __name__ == '__main__':
    unittest.main()
