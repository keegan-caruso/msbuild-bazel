"""Acquire checksum-pinned validation tooling without changing the SDK or PATH."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
pin = json.loads((ROOT / 'scripts/starlark-tools.json').read_text())['buildifier']
key = platform.system() + '-' + platform.machine()
if key not in pin['platforms']:
    raise SystemExit('No pinned Buildifier for ' + key)
artifact = pin['platforms'][key]
destination = ROOT / '.tools/bin/buildifier'
destination.parent.mkdir(parents=True, exist_ok=True)
if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != artifact['sha256']:
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        downloaded = Path(temporary) / 'buildifier'
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                        '--retry', '3', '--connect-timeout', '20', '--max-time', '300',
                        artifact['url'], '--output', str(downloaded)], check=True)
        if hashlib.sha256(downloaded.read_bytes()).hexdigest() != artifact['sha256']:
            raise SystemExit('Buildifier checksum mismatch')
        downloaded.chmod(0o755)
        downloaded.replace(destination)
print('Buildifier ' + pin['version'] + ': verified ' + key)
