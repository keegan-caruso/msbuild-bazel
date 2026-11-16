"""Exercise opaque TCP/UNIX transport and HTTPS endpoint guards."""
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/shared-cache-guest-relay.py'
spec = importlib.util.spec_from_file_location('relay', SCRIPT)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class RelayTests(unittest.TestCase):
    def test_endpoint_identity(self):
        self.assertEqual(relay.endpoint('https://cache.example:8443/path'), ('cache.example', 8443))
        self.assertEqual(relay.endpoint('https://cache.example'), ('cache.example', 443))
        for url in ('http://cache.example', 'https://127.0.0.1', 'https://user:secret@cache.example', 'https://bad%20host'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                relay.endpoint(url)

    def exercise_drain(self, upstream_action, expected, idle=0.2):
        with tempfile.TemporaryDirectory() as folder:
            unix_path = str(Path(folder)/'upstream.sock')
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(unix_path)
                listener.listen()
                listener.settimeout(3)
                finished = threading.Event()
                upstream_errors = []

                class ObservedForward(relay.Forward):
                    def handle(self):
                        try:
                            super().handle()
                        finally:
                            finished.set()

                def upstream():
                    try:
                        connection, _ = listener.accept()
                        with connection:
                            connection.settimeout(3)
                            while connection.recv(65536):
                                pass
                            upstream_action(connection, finished)
                    except Exception as error:
                        upstream_errors.append(error)

                thread = threading.Thread(target=upstream, daemon=True)
                thread.start()
                with relay.Relay(('127.0.0.1', 0), ObservedForward) as server:
                    server.socket_path = unix_path
                    server.drain_idle_seconds = idle
                    serve = threading.Thread(target=server.serve_forever, daemon=True)
                    serve.start()
                    try:
                        with socket.create_connection(server.server_address, timeout=3) as client:
                            client.sendall(b'request')
                            started = time.monotonic()
                            client.shutdown(socket.SHUT_WR)
                            response = b''
                            while True:
                                block = client.recv(65536)
                                if not block:
                                    break
                                response += block
                            self.assertEqual(response, expected)
                            self.assertTrue(finished.wait(2))
                            elapsed = time.monotonic() - started
                        thread.join(3)
                        self.assertFalse(thread.is_alive())
                        self.assertEqual(upstream_errors, [])
                        return elapsed
                    finally:
                        server.shutdown()
                        serve.join(3)

    def test_idle_opposite_peer_closes_after_bounded_drain(self):
        def hold(connection, finished):
            self.assertTrue(finished.wait(2))
        elapsed = self.exercise_drain(hold, b'', idle=0.15)
        self.assertGreaterEqual(elapsed, 0.10)
        self.assertLess(elapsed, 1.5)

    def test_delayed_response_after_half_close_is_preserved(self):
        def respond(connection, finished):
            time.sleep(0.05)
            connection.sendall(b'delayed response')
        self.exercise_drain(respond, b'delayed response', idle=0.3)

    def test_reverse_progress_extends_idle_deadline(self):
        def stream(connection, finished):
            for _ in range(6):
                time.sleep(0.06)
                connection.sendall(b'x')
        elapsed = self.exercise_drain(stream, b'xxxxxx', idle=0.15)
        self.assertGreater(elapsed, 0.30)

    def test_blocked_drain_send_is_bounded(self):
        writer, reader = socket.socketpair()
        with writer, reader:
            writer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            started = time.monotonic()
            result = relay.drain_send(writer, b'x' * (8 * 1024 * 1024), started + 0.2, 0.2)
            elapsed = time.monotonic() - started
            self.assertIsNone(result)
            self.assertGreaterEqual(elapsed, 0.10)
            self.assertLess(elapsed, 2)
            reader.settimeout(1)
            self.assertTrue(reader.recv(65536))

    def test_bidirectional_bytes_and_half_close(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            unix_path = str(root / 'upstream.sock')
            hosts, ready = root / 'hosts', root / 'ready'
            hosts.write_text('127.0.0.1 localhost\n')
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(unix_path)
                listener.listen()
                listener.settimeout(5)
                received = []

                def upstream():
                    # First connection is the relay's startup reachability probe.
                    probe, _ = listener.accept()
                    probe.close()
                    connection, _ = listener.accept()
                    with connection:
                        data = b''
                        while True:
                            block = connection.recv(65536)
                            if not block:
                                break
                            data += block
                        received.append(data)
                        connection.sendall(data[::-1])

                thread = threading.Thread(target=upstream, daemon=True)
                thread.start()
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0))
                    port = reservation.getsockname()[1]
                process = subprocess.Popen([sys.executable, str(SCRIPT), '--url', 'https://cache.example:' + str(port),
                                            '--socket', unix_path, '--hosts', str(hosts), '--ready', str(ready)])
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        self.assertIsNone(process.poll())
                        time.sleep(.01)
                    self.assertTrue(ready.exists())
                    self.assertIn('127.0.0.1 cache.example\n', hosts.read_text())
                    payload = bytes(range(256)) * 1024
                    with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
                        client.sendall(payload)
                        client.shutdown(socket.SHUT_WR)
                        response = b''
                        while True:
                            block = client.recv(65536)
                            if not block:
                                break
                            response += block
                    thread.join(5)
                    self.assertEqual(received, [payload])
                    self.assertEqual(response, payload[::-1])
                finally:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
