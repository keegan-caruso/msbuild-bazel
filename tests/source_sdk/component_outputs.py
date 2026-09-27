"""Bundle one VMR component's published artifacts using its upstream manifests.

Preserves manifest bytes and VMR-relative artifact paths. This is qualification
of the output boundary, not a replacement for MSBuild's package/version logic.
"""
import argparse
import json
import re
from pathlib import Path, PurePosixPath
import tarfile
import xml.etree.ElementTree as ET

from inventory import digest
from source_action_prepare import normalize


def published_files(root, component, configuration='Release'):
    root = root.resolve()
    if not component or component in {'.', '..'} or '/' in component or '\\' in component:
        raise ValueError('Expected one component name')
    if configuration not in {'Release', 'Debug'}:
        raise ValueError('Unsupported configuration')
    manifests = sorted((root / 'artifacts/obj/manifests' / configuration / component).glob('*.xml'))
    if not manifests:
        raise ValueError('No component manifests: ' + component)
    paths = {str(path.relative_to(root)) for path in manifests}
    for manifest in manifests:
        document = ET.parse(manifest).getroot()
        for asset in document:
            if asset.tag not in {'Package', 'Blob'}:
                continue
            name = asset.get('PipelineArtifactPath', '')
            if not name and document.get('PublishingVersion') == '3' and asset.tag == 'Package':
                package_id, version = asset.get('Id', ''), asset.get('Version', '')
                if not all(re.fullmatch(r'[A-Za-z0-9_.+-]+', value) for value in [package_id, version]):
                    raise ValueError('Invalid legacy package identity')
                shipping = 'NonShipping' if asset.get('NonShipping', '').lower() == 'true' else 'Shipping'
                name = f'artifacts/packages/{configuration}/{shipping}/{component}/{package_id}.{version}.nupkg'
            path = PurePosixPath(name)
            if not name or path.is_absolute() or '..' in path.parts or '\\' in name or str(path) != name:
                raise ValueError('Unsafe artifact path: ' + name)
            if not name.startswith('artifacts/'):
                raise ValueError('Artifact is outside artifacts/: ' + name)
            if asset.get('RepoOrigin') != component:
                raise ValueError('Artifact has unexpected RepoOrigin: ' + name)
            paths.add(name)
    for name in sorted(paths):
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or escaped artifact: ' + name)
    return sorted(paths)


def bundle(root, component, output, extra_trees=()):
    paths = set(published_files(root, component))
    for name in extra_trees:
        logical = PurePosixPath(name)
        if not name or name == '.' or logical.is_absolute() or '..' in logical.parts or str(logical) != name or '\\' in name:
            raise ValueError('Unsafe side-output tree: ' + name)
        tree = root / name
        if not tree.is_dir() or tree.is_symlink() or not tree.resolve().is_relative_to(root.resolve()):
            raise ValueError('Missing or escaped side-output tree: ' + name)
        files = []
        for entry in tree.rglob('*'):
            if entry.is_symlink():
                raise ValueError('Symlink in side-output tree: ' + str(entry))
            if entry.is_file():
                files.append(str(entry.relative_to(root)))
        if not files:
            raise ValueError('Empty side-output tree: ' + name)
        paths.update(files)
    paths = sorted(paths)
    report = {'component': component, 'files': []}
    with tarfile.open(output, 'w') as archive:
        for name in paths:
            path = root / name
            archive.add(path, arcname=name, filter=normalize)
            report['files'].append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    report['archiveSha256'] = digest(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('component')
    parser.add_argument('output', type=Path)
    parser.add_argument('--extra-tree', action='append', default=[], help='Explicit component side-output directory, relative to the VMR root')
    args = parser.parse_args()
    report = bundle(args.source.resolve(), args.component, args.output, args.extra_tree)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(args.component, len(report['files']), 'files', report['archiveSha256'])


if __name__ == '__main__':
    main()
