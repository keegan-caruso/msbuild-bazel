#!/usr/bin/env python3
"""Forward guest TCP to a mounted host socket without terminating TLS."""
import argparse
import errno
import ipaddress
from pathlib import Path
import select
import socket
import socketserver
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


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as upstream:
            upstream.connect(self.server.socket_path)
            peers = {self.request: upstream, upstream: self.request}
            while peers:
                readable, _, _ = select.select(list(peers), [], [])
                for source in readable:
                    data = source.recv(65536)
                    destination = peers[source]
                    if data:
                        destination.sendall(data)
                    else:
                        try:
                            destination.shutdown(socket.SHUT_WR)
                        except OSError as error:
                            if error.errno not in (errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE):
                                raise
                        del peers[source]


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
