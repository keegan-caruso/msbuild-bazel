#!/usr/bin/env python3
"""Task-owned bounded HTTP cache and opaque UNIX/TCP transport for qualification.

Keep the serve process on the producer host after its build guest stops. A
separate relay on a consumer host can target an encrypted Rex TCP forward.
Only this disposable service reads the phase file; managed services are untouched.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import socketserver
import threading
import time

from linux_action_recovery import Cache


class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 64
    drain_idle_seconds = 30


# Use the same tested half-close/drain pump in both transport directions.
spec = importlib.util.spec_from_file_location(
    'private_cache_guest_relay', Path(__file__).resolve().parents[2] / 'scripts/shared-cache-guest-relay.py')
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class Forward(relay.Forward):
    def connect_upstream(self):
        upstream = socket.create_connection(self.server.upstream, timeout=30)
        upstream.settimeout(None)
        return upstream


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['serve', 'relay'])
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18726)
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    if args.socket.exists():
        parser.error('Use a new task-owned socket path')
    args.socket.parent.mkdir(parents=True, exist_ok=True)
    cache = None
    if args.mode == 'serve':
        if args.root is None:
            parser.error('--root is required for serve')
        args.root.mkdir(parents=True, exist_ok=False)
        blobs = args.root / 'blobs'
        blobs.mkdir()

        class FixedCache(Cache):
            def server_bind(self):
                self.server_address = ('127.0.0.1', args.port)
                super().server_bind()

        cache = FixedCache(blobs, 1024**3)
        threading.Thread(target=cache.serve_forever, daemon=True).start()
        phase = args.root / 'phase'
        phase.write_text('seed\n')

        def metrics():
            while True:
                with cache.lock:
                    cache.phase = phase.read_text().strip()
                    report = {'phase': cache.phase, 'bytes': cache.used, 'limit': cache.limit,
                              'requests': {'|'.join(map(str, k)): v for k, v in sorted(cache.counts.items())}}
                temporary = args.root / 'metrics.tmp'
                temporary.write_text(json.dumps(report, indent=2) + '\n')
                temporary.replace(args.root / 'metrics.json')
                time.sleep(0.1)

        threading.Thread(target=metrics, daemon=True).start()
    try:
        with UnixServer(str(args.socket), Forward) as server:
            args.socket.chmod(0o600)
            server.upstream = ('127.0.0.1', args.port)
            print('Ready:', args.mode, args.socket, 'HTTP port', args.port, flush=True)
            server.serve_forever()
    finally:
        if cache:
            cache.shutdown()
            cache.server_close()
        args.socket.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
