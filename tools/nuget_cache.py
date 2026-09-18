"""Copy the selected restored NuGet closure into owned inputs; never build in it."""
import json
import os
import re
from pathlib import Path
import shutil

from preparation_identity import IdentityError, tree_snapshot
from portable_cache import valid_path


def default_cache():
    return Path(os.environ.get('NUGET_PACKAGES') or Path.home() / '.nuget/packages').expanduser().resolve()


def restore_metadata(path):
    return 'obj' in path.parts and (path.name in ('project.assets.json', 'project.nuget.cache') or
        path.name.endswith(('.nuget.g.props', '.nuget.g.targets', '.nuget.dgspec.json')))


def snapshot(path):
    value = tree_snapshot(path)
    if any(e['kind'] == 'symlink' for e in value['entries']): raise IdentityError('NuGet inputs contain symlinks')
    return value


def stage(source, destination, cache):
    """Use already-restored assets. Missing/corrupt packages require NuGet restore.

    Hash before/after copying; no links to the mutable global cache survive.
    Discovery and native preparation still verify archives against restore pins.
    Unrelated global packages are never scanned or copied.
    """
    if Path(destination).absolute() != Path(destination).resolve():
        raise IdentityError('linked or noncanonical NuGet staging destination')
    source, destination, cache = (Path(p).resolve() for p in (source, destination, cache))
    if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination) or destination == cache or destination.is_relative_to(cache) or cache.is_relative_to(destination):
        raise IdentityError('NuGet staging paths must be disjoint')
    before = snapshot(source)
    local = source / '.nuget/packages'
    packages = set(); external = False
    for entry in before['entries']:
        path = Path(entry['path'])
        if entry['kind'] != 'file' or path.name != 'project.assets.json' or 'obj' not in path.parts: continue
        assets = json.loads((source / path).read_text())
        folders = {Path(p).resolve() for p in assets.get('packageFolders', {})}
        if folders - {local, cache}: raise IdentityError('restore uses a different NuGet cache; select it with --nuget-packages')
        if cache in folders and cache != local:
            if local in folders: raise IdentityError('multiple restored package roots are not supported')
            external = True
            for library in assets.get('libraries', {}).values():
                if library.get('type') != 'package': continue
                relative = library['path']
                if not valid_path(relative) or len(relative.split('/')) != 2: raise IdentityError('invalid restored package path')
                packages.add(relative)
    if not external: return source, dict(staged=False, packages=0, bytes=0)
    if destination.exists(): shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    package_root = destination / '.nuget/packages'
    if package_root.exists(): shutil.rmtree(package_root)
    package_root.mkdir(parents=True)
    total = 0
    for relative in sorted(packages):
        original = cache / relative
        if not original.is_dir(): raise IdentityError('missing NuGet package; run restore: ' + relative)
        if any(p.is_symlink() for p in (cache / relative.split('/')[0], original)): raise IdentityError('linked NuGet package')
        expected = snapshot(original)
        target = package_root / relative
        shutil.copytree(original, target)
        if snapshot(original) != expected or snapshot(target)['sha256'] != expected['sha256']:
            raise IdentityError('NuGet package changed while staging: ' + relative)
        total += expected['bytesHashed']
    if snapshot(source) != before: raise IdentityError('restored source changed while staging NuGet inputs')
    replacements = {str(cache).encode(): str(package_root).encode(), str(source).encode(): str(destination).encode()}
    pattern = re.compile(b'(' + b'|'.join(re.escape(p) for p in sorted(replacements, key=len, reverse=True)) + b')(?=/|[\"\'<\\s]|$)')
    for path in destination.rglob('*'):
        if path.is_file() and restore_metadata(path.relative_to(destination)):
            path.write_bytes(pattern.sub(lambda match: replacements[match[0]], path.read_bytes()))
    return destination, dict(staged=True, packages=len(packages), bytes=total)
