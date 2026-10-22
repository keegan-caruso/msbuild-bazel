"""Run the pinned CMS app and verify its setup page and embedded assets."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ASSETS = {
    '/OrchardCore.Setup/Styles/setup.min.css': 'f2ef0e79a938781eb7b4108d68e5ebd809e4d6f6687c77dad058a95b559a2fa8',
    '/OrchardCore.Setup/Scripts/setup/setup.min.js': '0ae0a82143492a81c236e0e7006cb10b9832d31b9c3c46eb8e26ca5f5af261d9',
    '/OrchardCore.Resources/Vendor/fontawesome-free/css/all.min.css': 'e0b69df26e19596d4b81bf7eb0c54b6047e7221ec18d5d4d40c11eefd3ef8a4b',
}


def check(command, log, cwd=None):
    with socket.socket() as port:
        port.bind(('127.0.0.1', 0))
        address = 'http://127.0.0.1:' + str(port.getsockname()[1])
    with log.open('w') as stream:
        process = subprocess.Popen(list(map(str, command)) + ['--urls', address], cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            end = time.monotonic() + 45
            while True:
                assert process.poll() is None, log.read_text()
                try:
                    with urllib.request.urlopen(address, timeout=3) as response:
                        page = response.read().decode()
                        assert response.status == 200 and 'setup' in page.lower(), page[:300]
                    break
                except (urllib.error.URLError, TimeoutError):
                    assert time.monotonic() < end, log.read_text()
                    time.sleep(0.2)
            for path, expected in ASSETS.items():
                with urllib.request.urlopen(address + path, timeout=10) as response:
                    assert response.status == 200 and hashlib.sha256(response.read()).hexdigest() == expected, path
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=20)
    print(json.dumps(dict(smoke='setup page and three embedded assets', status=200)), flush=True)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(dir=os.environ.get('TEST_TMPDIR')) as temporary:
        log = Path(temporary) / 'http.log'
        try:
            check(sys.argv[1:], log)
        except BaseException:
            if log.exists():
                print(log.read_text(), file=sys.stderr)
            raise
