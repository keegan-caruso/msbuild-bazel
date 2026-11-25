"""Consumer-local HTTP cache guard: a remote miss stops the local Bazel group.

The upstream service must independently restrict access and reject writes. This
proxy rejects writes too, and counts streamed response body bytes, not wire bytes.
"""
import argparse
import collections
import datetime
import json
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


def terminate_owned(process, grace):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    except ProcessLookupError:
        process.wait(timeout=10)


class ReadOnlyCacheProxy(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, upstream, abort_grace=5):
        address = urlsplit(upstream)
        if address.scheme not in ['http', 'https'] or not address.hostname or address.username or \
                address.password or address.query or address.fragment:
            raise ValueError('Require an HTTP(S) upstream without credentials/query/fragment')
        self.upstream = address
        self.active = None
        self.abort_grace = abort_grace
        self.phase = 'recover'
        self.lock = threading.Lock()
        self.counts, self.get_bytes, self.misses = collections.Counter(), collections.Counter(), []
        super().__init__(('127.0.0.1', 0), ProxyHandler)

    def stop_on_miss(self, method, path, status):
        with self.lock:
            self.misses.append(dict(phase=self.phase, method=method, path=path, status=status))
            active = self.active
        if active is not None:
            # Do not return a miss while the owned process can fall back locally.
            terminate_owned(active, self.abort_grace)


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

    def reply_error(self, status):
        try:
            self.reply(status)
        except (BrokenPipeError, ConnectionResetError):
            # The owned requester may already have exited after the miss guard.
            self.close_connection = True

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
            self.reply_error(400)
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
                self.reply_error(response.status)
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
                self.reply_error(502)
            self.close_connection = True
        finally:
            connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', required=True, help='read-only upstream HTTP(S) cache')
    parser.add_argument('--report', required=True, type=Path, help='new JSON receipt')
    parser.add_argument('--phase', default='recover')
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--abort-grace', type=float, default=5)
    parser.add_argument('command', nargs=argparse.REMAINDER,
                        help='-- BAZEL --batch --output_base=FRESH build|test ...')
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    actions = [index for index, value in enumerate(command) if value in ['build', 'test']]
    if not command or len(actions) != 1 or '--batch' not in command or not any(
            value.startswith('--output_base=') for value in command):
        parser.error('explicit Bazel --batch, --output_base= and one build/test phase are required')
    if args.report.exists() or args.timeout <= 0 or args.abort_grace <= 0:
        parser.error('require a new report and positive timeout/grace')
    if any(value.startswith(('--remote_cache', '--remote_executor', '--remote_upload_local_results'))
           for value in command):
        parser.error('cache/executor/upload settings are owned by this read-only guard')
    proxy = ReadOnlyCacheProxy(args.cache, args.abort_grace)
    proxy.phase = args.phase
    url = 'http://127.0.0.1:' + str(proxy.server_port)
    index = actions[0] + 1
    command = command[:index] + ['--remote_cache=' + url, '--remote_upload_local_results=false',
                                '--remote_cache_async=false'] + command[index:]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = dict(upstream=args.cache, phase=args.phase, command=command,
                  startedUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  bodyByteScope='successful streamed writes; excludes headers/transport overhead')
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    process = None
    started = time.monotonic()
    prior_term = signal.getsignal(signal.SIGTERM)

    def interrupt(*_):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, interrupt)
    try:
        process = subprocess.Popen(command, start_new_session=True)
        with proxy.lock:
            proxy.active = process
        process.wait(timeout=args.timeout)
        report['returnCode'] = process.returncode
    except BaseException as error:
        report['error'] = repr(error)
        if process is not None:
            terminate_owned(process, args.abort_grace)
            report['returnCode'] = process.returncode
    finally:
        with proxy.lock:
            proxy.active = None
            report.update(requests={'|'.join(map(str, key)): count for key, count in proxy.counts.items()},
                          getPayloadBytes=dict(proxy.get_bytes), misses=list(proxy.misses))
        report.update(wallSeconds=time.monotonic()-started,
                      passed=report.get('returnCode') == 0 and not report.get('error') and
                      not report['misses'] and not any(key[1] == 'PUT' for key in proxy.counts))
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=10)
        signal.signal(signal.SIGTERM, prior_term)
        temporary = args.report.with_name(args.report.name + '.tmp')
        temporary.write_text(json.dumps(report, indent=2) + '\n')
        temporary.replace(args.report)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
