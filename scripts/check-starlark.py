"""Read-only formatting/lint gate for owned sources or a generated workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Policy: the pinned Buildifier release's complete default warning set.
# No global suppressions; compatibility exceptions live beside the declaration.


def check(workspace=None):
    binary = ROOT / '.tools/bin/buildifier'
    pin = json.loads((ROOT / 'scripts/starlark-tools.json').read_text())['buildifier']
    artifact = pin['platforms'][platform.system() + '-' + platform.machine()]
    if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest() != artifact['sha256']:
        raise SystemExit('Run bash scripts/tooling.sh setup-starlark to acquire pinned Buildifier')
    if workspace:
        # Generated workspaces own only these root files; never follow SDK/Bazel
        # symlinks into downloads, packages, or output trees.
        files = sorted(p for p in Path(workspace).iterdir() if p.is_file() and
                       (p.suffix == '.bzl' or p.name in ('BUILD', 'BUILD.bazel', 'MODULE.bazel')))
    elif (ROOT / '.git').exists():
        names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
        files = sorted({ROOT / name for name in names if name and
                        (name.endswith('.bzl') or Path(name).name in ('BUILD', 'BUILD.bazel', 'MODULE.bazel'))})
    else:
        # Apple container copies the source tree without Git metadata. Retain the
        # same owned-file boundary without following tools or Bazel symlinks.
        excluded = {'.git', '.tools', '.cache', 'artifacts', 'bin', 'obj', '__pycache__'}
        files = []
        for directory, dirs, names in os.walk(ROOT, followlinks=False):
            dirs[:] = [d for d in dirs if d not in excluded and not d.startswith('bazel-')
                       and not (Path(directory) / d).is_symlink()]
            files.extend(Path(directory) / name for name in names
                         if (name.endswith('.bzl') or name in ('BUILD', 'BUILD.bazel', 'MODULE.bazel'))
                         and not (Path(directory) / name).is_symlink())
        files.sort()
    if not files:
        raise SystemExit('No owned Starlark files found')
    result = subprocess.run([str(binary), '-mode=check', '-lint=warn',
                             *map(str, files)])
    if result.returncode:
        raise SystemExit(result.returncode)
    print(f'Starlark formatting/lint passed: {len(files)} files')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path)
    check(parser.parse_args().workspace)
