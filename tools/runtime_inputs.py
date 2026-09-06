"""Conservative Nix reference closure; not discovery of arbitrary host reads."""
import json
from pathlib import Path
import subprocess
import shutil


def store_root(path):
    resolved = Path(path).resolve()
    if resolved.parts[:3] != ('/', 'nix', 'store') or len(resolved.parts) < 4:
        raise ValueError('runtime closure requires Nix store tools: ' + str(resolved))
    return Path(*resolved.parts[:4])


def prepare(workspace, paths):
    roots = sorted({str(store_root(path)) for path in paths if path})
    nix_store = shutil.which('nix-store') or '/nix/var/nix/profiles/default/bin/nix-store'
    result = subprocess.run([nix_store, '--query', '--requisites', *roots],
                            check=True, text=True, capture_output=True)
    closure = sorted(set(result.stdout.splitlines()))
    if not set(roots) <= set(closure):
        raise ValueError('runtime closure omitted a root')
    files = []
    for name in closure:
        root = Path(name)
        if store_root(root) != root or not root.exists():
            raise ValueError('unsupported runtime store entry: ' + name)
        if root.is_file():
            files.append(root.name)
            continue
        # Nix references enumerate directory symlink targets separately;
        # walking them here would duplicate payloads.
        for path in sorted(root.rglob('*')):
            if path.is_file():
                files.append(root.name + '/' + path.relative_to(root).as_posix())
    manifest = dict(schemaVersion=1, roots=roots, storePaths=closure, files=files,
                    boundary='Nix references only; host OS and dynamic host reads remain outside this closure')
    (workspace / 'runtime-closure.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest
