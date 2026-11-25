#!/usr/bin/env python3
"""Portable protocol controls for the cross-host qualification counter."""
import collections
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import sys
import socket
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_build'))

from cross_host_recovery import Proxy
from linux_action_recovery import Cache
from private_http_cache import Forward, UnixServer


class UnknownLength(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'connection-delimited')

    def log_message(self, *_):
        pass


class JsonUpload(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.headers.get('Accept') == 'application/json' else 400)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', '18')
        self.end_headers()
        self.wfile.write(b'{"outputFiles":[]}')

    def do_PUT(self):
        size = int(self.headers['Content-Length'])
        valid = (self.headers.get('Content-Type') == 'application/json' and
                 self.headers.get('Content-Encoding') == 'identity' and
                 self.rfile.read(size) == b'{"outputFiles":[]}')
        self.send_response(200 if valid else 400)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *_):
        pass


class ProxyTests(unittest.TestCase):
    def start(self, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def proxy(self, upstream):
        proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        proxy.upstream = 'http://127.0.0.1:' + str(upstream.server_port)
        proxy.readonly = False
        proxy.counts = collections.Counter()
        proxy.lock = threading.Lock()
        return self.start(proxy)

    def connection(self, proxy):
        connection = http.client.HTTPConnection('127.0.0.1', proxy.server_port, timeout=5)
        self.addCleanup(connection.close)
        return connection

    def test_chunked_upload_head_get_and_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            upstream = self.start(Cache(Path(folder), 1024**2))
            proxy = self.proxy(upstream)
            connection = self.connection(proxy)
            data = b'hello streamed cache'
            path = '/cas/' + hashlib.sha256(data).hexdigest()
            connection.request('PUT', path, body=iter([data[:5], data[5:]]), encode_chunked=True)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            proxy.readonly = True
            connection.request('HEAD', path)
            response = connection.getresponse()
            self.assertEqual(int(response.getheader('Content-Length')), len(data))
            self.assertEqual(response.read(), b'')
            connection.request('GET', path)
            self.assertEqual(connection.getresponse().read(), data)
            connection.request('PUT', path, body=data)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            self.assertEqual(proxy.counts['PUT'], 2)
            self.assertEqual(proxy.counts['PUTRequestBytes'], len(data) * 2)
            self.assertEqual(proxy.counts['GETResponseBytes'], len(data))

    def test_json_action_result_headers(self):
        proxy = self.proxy(self.start(ThreadingHTTPServer(('127.0.0.1', 0), JsonUpload)))
        connection = self.connection(proxy)
        connection.request('PUT', '/rules-msbuild/ac/key', body=b'{"outputFiles":[]}',
                           headers={'Content-Type': 'application/json', 'Content-Encoding': 'identity'})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        connection.request('GET', '/rules-msbuild/ac/key', headers={'Accept': 'application/json'})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('Content-Type'), 'application/json')
        self.assertEqual(response.read(), b'{"outputFiles":[]}')

    def test_unknown_response_length(self):
        proxy = self.proxy(self.start(ThreadingHTTPServer(('127.0.0.1', 0), UnknownLength)))
        connection = self.connection(proxy)
        connection.request('GET', '/stream')
        response = connection.getresponse()
        self.assertEqual(response.getheader('Connection'), 'close')
        self.assertEqual(response.read(), b'connection-delimited')

    def test_private_cache_json_and_unix_transport(self):
        with tempfile.TemporaryDirectory() as folder:
            upstream = self.start(Cache(Path(folder), 1024**2))
            path = str(Path(folder) / 'relay.sock')
            relay = self.start(UnixServer(path, Forward))
            relay.upstream = ('127.0.0.1', upstream.server_port)
            connection = http.client.HTTPConnection('unused', timeout=5)
            connection.sock = socket.socket(socket.AF_UNIX)
            connection.sock.settimeout(5)
            connection.sock.connect(path)
            self.addCleanup(connection.close)
            key = '/rules-msbuild/ac/' + 'a' * 64
            payload = b'{"outputFiles":[]}'
            connection.request('PUT', key, body=payload, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            connection.request('GET', key, headers={'Accept': 'application/json'})
            self.assertEqual(connection.getresponse().read(), payload)
            upstream.phase = 'consumer'
            connection.request('PUT', key, body=payload)
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()

    def test_truncated_trailers_terminate(self):
        # Exercise the decoder directly so expected EOF does not produce an
        # HTTP server traceback or leave an orphan connection thread.
        import io
        handler = object.__new__(Proxy)
        handler.headers = {'Transfer-Encoding': 'chunked'}
        handler.rfile = io.BytesIO(b'1\r\nx\r\n0\r\n')
        with self.assertRaises(EOFError):
            handler.handle_request()


if __name__ == '__main__':
    unittest.main()
