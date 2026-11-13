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
