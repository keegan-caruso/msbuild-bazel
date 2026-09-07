"""Verify and stage each configured node's managed NuGet closure."""
import base64
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile


def package_plan(workspace, project):
    project = Path(project)
    assets = json.loads((workspace / project.parent / 'obj/project.assets.json').read_text())
    libraries = {k: v for k, v in assets['libraries'].items() if v['type'] == 'package'}
    source = workspace / project
    if not source.is_file() or not source.resolve().is_relative_to(workspace):
        raise ValueError('missing-input: missing or escaping input: workspace/' + project.as_posix())
    try:
        tree = ET.parse(source)
    except ET.ParseError as error:
        raise ValueError('stale-manifest: stale graph input: workspace/' + project.as_posix()) from error
    for reference in tree.getroot().iter('PackageReference'):
        version = reference.get('Version', '')
        if not (version.startswith('[') and version.endswith(']') and ',' not in version):
            raise ValueError('unsupported-package: exact inline version required')
        identity = reference.get('Include', '') + '/' + version[1:-1]
        if identity.lower() not in {k.lower() for k in libraries}:
            raise ValueError('stale-restore: package reference differs from restored version')
    if not libraries:
        return assets, libraries
    if not assets.get('targets') or any('path' not in item or 'sha512' not in item for item in libraries.values()):
        raise ValueError('unsupported-package: incomplete restored package metadata')
    for target in assets['targets'].values():
        for identity, entry in target.items():
            if identity in libraries and any(entry.get(k) for k in ('native', 'runtimeTargets', 'build', 'buildMultiTargeting', 'buildTransitive', 'contentFiles')):
                raise ValueError('unsupported-package: only managed ref/lib assets are supported')
    return assets, libraries


def stage(workspace, project, output, node_id):
    assets, libraries = package_plan(workspace, project)
    manifest = {'schemaVersion': 1, 'packages': []}
    paths = []
    for identity, library in sorted(libraries.items()):
        package_id, version = identity.split('/')
        relative = package_id.lower() + '/' + version
        if library['path'] != relative or '..' in Path(relative).parts:
            raise ValueError('unsupported-package: invalid package path')
        folder = workspace / '.nuget/packages' / relative
        archive = folder / (package_id.lower() + '.' + version + '.nupkg')
        if not archive.is_file(): raise ValueError('missing-input: ' + str(archive))
        raw = archive.read_bytes()
        sha512 = base64.b64encode(hashlib.sha512(raw).digest()).decode('ascii')
        if sha512 != library['sha512']:
            raise ValueError('hash-mismatch: package archive disagrees with restore')
        files = []
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if entry.is_dir(): continue
                name = entry.filename
                if name.endswith('.nuspec'): name = name.lower()
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError('unsupported-package: escaping archive entry')
                if name.split('/')[0].lower() in ('runtimes', 'native', 'analyzers', 'build', 'buildtransitive', 'buildmultitargeting', 'content', 'contentfiles', 'tools'):
                    raise ValueError('unsupported-package: only managed ref/lib payloads supported')
                contents = package.read(entry)
                source = folder / name
                if not source.is_file(): raise ValueError('missing-input: ' + str(source))
                if source.read_bytes() != contents: raise ValueError('hash-mismatch: package payload ' + name)
                target = output / 'packages' / relative / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
                paths.append(target.relative_to(output).as_posix())
                files.append(dict(path=name, size=len(contents), sha256=hashlib.sha256(contents).hexdigest()))
        name = package_id.lower() + '.' + version + '.nupkg.sha512'
        marker = sha512.encode('ascii')
        target = output / 'packages' / relative / name
        target.write_bytes(marker)
        paths.append(target.relative_to(output).as_posix())
        files.append(dict(path=name, size=len(marker), sha256=hashlib.sha256(marker).hexdigest()))
        manifest['packages'].append(dict(id=package_id, version=version, path=relative,
                                        archiveSha256=hashlib.sha256(raw).hexdigest(), files=files))
    path = output / 'package-manifests' / (node_id + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, sort_keys=True))
    return path.relative_to(output).as_posix(), sorted(paths)
