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


def read_recipe(architecture='arm64'):
    if architecture not in ('arm64', 'x64'):
        raise ValueError('Unsupported source-runtime architecture: ' + architecture)
    recipe = RECIPE if architecture == 'arm64' else RECIPE.with_name('source-x64.json')
    value = json.loads(recipe.read_text())
    if value['schemaVersion'] != 1 or value['platform'] != 'linux-' + architecture or value['sdk']['platform'] != value['platform']:
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


def stage_source(destination, expected, supplied):
    if destination.exists():
        if digest(destination) != expected:
            raise ValueError('Retained download changed: ' + str(destination))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.partial')
    # Never reuse a partial inode from an interrupted hardlink/copy.
    temporary.unlink(missing_ok=True)
    if digest(supplied) != expected:
        raise ValueError('Supplied source archive differs from the pinned source')
    try:
        os.link(supplied, temporary)
    except OSError:
        import shutil
        shutil.copy2(supplied, temporary)
    if digest(temporary) != expected:
        temporary.unlink()
        raise ValueError('Staged source archive differs from the pinned source')
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
        state_path = base/'setup.json'
        if not state_path.is_file():
            raise ValueError('Refusing to resume an unowned output directory')
        state = json.loads(state_path.read_text())
        if state.get('kind') != kind or state.get('version') != 1:
            raise ValueError('Output belongs to another workflow')
        return state
    base.mkdir(parents=True, mode=0o700)
    return None


def selected_bazel_version():
    """Use an explicit override, otherwise the rules checkout's pin."""
    return os.environ.get('USE_BAZEL_VERSION') or (ROOT / '.bazelversion').read_text().strip()


def validate_bazel_version(state):
    if state.get('bazelVersion') != selected_bazel_version():
        raise ValueError('Bazel version changed; use a fresh output directory')


def project_cache_read_only(state=None):
    """Retain an owned workflow's publication policy when the host env is absent."""
    key = 'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY'
    recorded = (state or {}).get('projectCacheReadOnly', '0')
    selected = os.environ.get(key, recorded)
    if selected not in ('0', '1') or recorded not in ('0', '1'):
        raise ValueError(key + ' must be 0 or 1')
    if state is not None and selected != recorded:
        raise ValueError('Project-cache publication policy changed; use a fresh output directory')
    return selected


def bazel_cache_read_only(state=None, supplied=None):
    recorded = state.get('bazelCacheReadOnly', False) if state is not None else False
    if type(recorded) is not bool:
        raise ValueError('Invalid saved Bazel cache policy')
    if state is not None and supplied is not None and supplied != recorded:
        raise ValueError('Bazel cache policy changed; use a fresh directory')
    return recorded if state is not None else bool(supplied)
