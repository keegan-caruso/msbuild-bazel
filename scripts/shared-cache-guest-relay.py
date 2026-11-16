#!/usr/bin/env python3
"""Forward guest TCP to a mounted host socket without terminating TLS."""
import argparse
import errno
import ipaddress
from pathlib import Path
import select
import socket
import socketserver
import time
from urllib.parse import urlsplit


def endpoint(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Relay requires an HTTPS cache URL with a DNS hostname and no credentials.')
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError('Relay requires a DNS hostname to preserve TLS identity.')
    hostname = parsed.hostname
    if not all(c.isascii() and (c.isalnum() or c in '.-') for c in hostname):
        raise ValueError('Invalid relay hostname.')
    return hostname, parsed.port or 443


class Relay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    drain_idle_seconds = 30


def drain_send(destination, data, deadline, idle_seconds):
    """Forward reverse bytes without allowing a blocked write to outlive idle drain."""
    remaining = memoryview(data)
    while remaining:
        timeout = deadline - time.monotonic()
        if timeout <= 0:
            return None
        destination.settimeout(timeout)
        try:
            sent = destination.send(remaining)
        except socket.timeout:
            return None
        if not sent:
            return None
        remaining = remaining[sent:]
        deadline = time.monotonic() + idle_seconds
    return deadline


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
                upstream.connect(self.server.socket_path)
                peers = {self.request: upstream, upstream: self.request}
                deadline = None
                idle_seconds = self.server.drain_idle_seconds
                while peers:
                    timeout = None if deadline is None else deadline - time.monotonic()
                    if timeout is not None and timeout <= 0:
                        return
                    readable, _, _ = select.select(list(peers), [], [], timeout)
                    if not readable:
                        return
                    for source in readable:
                        data = source.recv(65536)
                        destination = peers[source]
                        if data:
                            if deadline is None:
                                destination.sendall(data)
                            else:
                                deadline = drain_send(destination, data, time.monotonic() + idle_seconds, idle_seconds)
                                if deadline is None:
                                    return
                        else:
                            try:
                                destination.shutdown(socket.SHUT_WR)
                            except OSError as error:
                                if error.errno not in (errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE, errno.ESHUTDOWN):
                                    raise
                            del peers[source]
                            if deadline is None:
                                deadline = time.monotonic() + idle_seconds
        except OSError as error:
            # Peers may disappear while a response is draining.
            if isinstance(error, socket.timeout) or error.errno in (errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE, errno.ESHUTDOWN, errno.ECONNABORTED):
                return
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--hosts', type=Path, default=Path('/etc/hosts'))
    parser.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args()
    hostname, port = endpoint(args.url)
    with Relay(('127.0.0.1', port), Forward) as server:
        server.socket_path = args.socket
        # Verify the mount is reachable before changing name resolution.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.connect(args.socket)
        with args.hosts.open('a') as hosts:
            hosts.write('\n127.0.0.1 ' + hostname + '\n')
        args.ready.touch()
        server.serve_forever()


if __name__ == '__main__':
    main()
