"""Owned state and pinned inputs shared by source-runtime setup entry points."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RECIPE = ROOT / 'examples/source-runtime-app/source.json'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_recipe():
    value = json.loads(RECIPE.read_text())
    if value['schemaVersion'] != 1 or value['platform'] != 'linux-arm64':
        raise ValueError('Unsupported source-runtime recipe')
    if value['sdk']['version'] != json.loads((ROOT / 'global.json').read_text())['sdk']['version']:
        raise ValueError('Source-runtime bootstrap SDK differs from the repository pin')
    return value


def save(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def run(command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


def acquire(destination, url, expected, supplied=None):
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError('Retained download changed: ' + str(destination))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.partial')
    # An interrupted hardlink/copy must never become curl's output inode.
    temporary.unlink(missing_ok=True)
    if supplied:
        if digest(supplied) != expected:
            raise ValueError('Supplied source archive differs from the pinned source')
        try:
            os.link(supplied, temporary)
        except OSError:
            import shutil
            shutil.copy2(supplied, temporary)
    else:
        run(['curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '20',
             '--max-time', '600', '--output', temporary, url])
    if digest(temporary) != expected:
        temporary.unlink()
        raise ValueError('Download hash differs: ' + url)
    temporary.replace(destination)


def rules_identity():
    if (ROOT / '.git').exists():
        paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        paths = [ROOT / name for name in paths if name]
    else:
        skipped = {'.git', '.tools', '.cache', 'artifacts', 'bin', 'obj', '__pycache__'}
        paths = []
        for directory, folders, files in os.walk(ROOT):
            folders[:] = [name for name in folders if name not in skipped and not name.startswith('bazel-')]
            paths.extend(Path(directory) / name for name in files if not name.endswith('.pyc'))
    value = hashlib.sha256()
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Rules snapshot requires independent regular files: ' + str(path))
        value.update(str(path.relative_to(ROOT)).encode() + b'\0' + digest(path).encode() + b'\n')
    return value.hexdigest()


def owned_output(base, resume, kind):
    if base.exists():
        if not resume:
            raise ValueError('Use a fresh output directory or --resume')
        state_path = base/'setup.json'
        if not state_path.is_file():
            raise ValueError('Refusing to resume an unowned output directory')
        state = json.loads(state_path.read_text())
        if state.get('kind') != kind:
            raise ValueError('Output belongs to another workflow')
        return state
    base.mkdir(parents=True, mode=0o700)
    return None
