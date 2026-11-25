"""Consumer-local HTTP cache guard: a remote miss stops the local Bazel group.

The upstream service must independently restrict access and reject writes. This
proxy rejects writes too, and counts streamed response body bytes, not wire bytes.
"""
import collections
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import signal
import threading
from urllib.parse import urlsplit


class ReadOnlyCacheProxy(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, upstream):
        address = urlsplit(upstream)
        if address.scheme not in ['http', 'https'] or not address.hostname or address.username or \
                address.password or address.query or address.fragment:
            raise ValueError('Require an HTTP(S) upstream without credentials/query/fragment')
        self.upstream = address
        self.active = None
        self.phase = 'recover'
        self.lock = threading.Lock()
        self.counts, self.get_bytes, self.misses = collections.Counter(), collections.Counter(), []
        super().__init__(('127.0.0.1', 0), ProxyHandler)

    def stop_on_miss(self, method, path, status):
        with self.lock:
            self.misses.append(dict(phase=self.phase, method=method, path=path, status=status))
            active = self.active
        if active is not None:
            try:
                os.killpg(active.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def record(self, method, status):
        with self.server.lock:
            self.server.counts[(self.server.phase, method, status)] += 1

    def reply(self, status, size=0):
        self.send_response(status)
        self.send_header('Content-Length', str(size))
        self.end_headers()

    def do_PUT(self):
        self.record('PUT', 403)
        self.close_connection = True
        self.reply(403)

    def do_HEAD(self):
        self.forward('HEAD')

    def do_GET(self):
        self.forward('GET')

    def forward(self, method):
        if not re.fullmatch(r'/(?:ac|cas|rules-msbuild/ac)/[0-9a-f]{64}', self.path):
            self.server.stop_on_miss(method, self.path, 400)
            self.record(method, 400)
            self.reply(400)
            return
        upstream = self.server.upstream
        connection_type = HTTPSConnection if upstream.scheme == 'https' else HTTPConnection
        connection = connection_type(upstream.hostname, upstream.port, timeout=120)
        replied = False
        try:
            connection.request(method, upstream.path.rstrip('/') + self.path)
            response = connection.getresponse()
            if response.status != 200:
                self.server.stop_on_miss(method, self.path, response.status)
                self.record(method, response.status)
                self.reply(response.status)
                return
            length = int(response.getheader('Content-Length'))
            if length < 0 or response.getheader('Content-Encoding'):
                raise ValueError('Upstream requires a bounded unencoded response')
            self.record(method, 200)
            self.reply(200, length)
            replied = True
            if method == 'GET':
                remaining = length
                while remaining:
                    block = response.read(min(1024 * 1024, remaining))
                    if not block:
                        raise IOError('Incomplete upstream response')
                    self.wfile.write(block)
                    remaining -= len(block)
                    with self.server.lock:
                        self.server.get_bytes[self.server.phase] += len(block)
        except Exception as error:
            self.server.stop_on_miss(method, self.path, type(error).__name__)
            self.record(method, 502)
            if not replied:
                self.reply(502)
            self.close_connection = True
        finally:
            connection.close()
