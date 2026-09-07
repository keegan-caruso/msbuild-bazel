"""Verify and stage each configured node's managed NuGet closure."""
import base64
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

PILOT_PACKAGES = json.loads((Path(__file__).with_name('pilot-package-policy.json')).read_text())

def selected_version(package_id, version):
    if version.startswith('[') and version.endswith(']') and ',' not in version:
        return version[1:-1]
    if (package_id + '/' + version).lower() in PILOT_PACKAGES:
        return version
    raise ValueError('unsupported-package: exact inline version or qualified pilot version required')


def metadata(reference, name):
    if name in reference.attrib:
        return reference.attrib[name]
    return next((child.text or '' for child in reference if child.tag.rsplit('}', 1)[-1] == name), None)


def privacy(value):
    flags = {flag.strip().lower() for flag in (value or '').replace(',', ';').split(';') if flag.strip()}
    if not flags or flags == {'contentfiles', 'analyzers', 'build'}:
        return 'default'
    if flags in ({'all'}, {'none'}):
        return next(iter(flags))
    raise ValueError('unsupported-package: PrivateAssets must be default, all or none')


def package_plan(workspace, project, assets_file=None):
    project = Path(project)
    assets = json.loads((workspace / (assets_file or project.parent / 'obj/project.assets.json')).read_text())
    libraries = {k: v for k, v in assets['libraries'].items() if v['type'] == 'package'}
    source = workspace / project
    if not source.is_file() or not source.resolve().is_relative_to(workspace):
        raise ValueError('missing-input: missing or escaping input: workspace/' + project.as_posix())
    try:
        tree = ET.parse(source)
    except ET.ParseError as error:
        raise ValueError('stale-manifest: stale graph input: workspace/' + project.as_posix()) from error
    direct = assets.get('project', {}).get('frameworks', {}).get('net10.0', {}).get('dependencies', {})
    direct = {name.lower(): value for name, value in direct.items()}
    parents = {child: parent for parent in tree.iter() for child in parent}
    for reference in tree.getroot().iter():
        if reference.tag.rsplit('}', 1)[-1] != 'PackageReference':
            continue
        ancestor = reference
        conditional = False
        while ancestor is not None:
            conditional |= 'Condition' in ancestor.attrib
            ancestor = parents.get(ancestor)
        if conditional:
            # Actual active items are checked by evaluated GraphExport revalidation.
            continue
        package_id = reference.get('Include') or reference.get('Update')
        if package_id is None:
            continue
        version = reference.get('Version')
        if 'Include' in reference.attrib or version is not None:
            version = version or ''
            identity = package_id + '/' + selected_version(package_id, version)
            if identity.lower() not in {k.lower() for k in libraries}:
                raise ValueError('stale-restore: package reference differs from restored version')
        # This early guard preserves stale-restore diagnostics for direct literal
        # edits. Imported/property-derived metadata is checked after evaluation
        # by GraphExport, before any fresh manifest can be published.
        current = metadata(reference, 'PrivateAssets')
        if current is not None and '$(' not in current and '@(' not in current:
            saved = direct.get(package_id.lower())
            if saved is None or privacy(current) != privacy(saved.get('suppressParent')):
                raise ValueError('stale-restore: PrivateAssets differs from restore: ' + package_id)
        for name, allowed in (('IncludeAssets', 'all'), ('ExcludeAssets', 'none')):
            value = metadata(reference, name)
            if value and '$(' not in value and '@(' not in value and value.lower() != allowed:
                raise ValueError('unsupported-package: nondefault ' + name)
    if not libraries:
        return assets, libraries
    if not assets.get('targets') or any('path' not in item or 'sha512' not in item for item in libraries.values()):
        raise ValueError('unsupported-package: incomplete restored package metadata')
    for target in assets['targets'].values():
        for identity, entry in target.items():
            if identity in libraries and any(entry.get(k) for k in ('native', 'runtimeTargets', 'resource', 'build', 'buildMultiTargeting', 'buildTransitive', 'contentFiles') if k.lower() not in PILOT_PACKAGES.get(identity.lower(), {}).get('assetRoles', [])):
                raise ValueError('unsupported-package: only managed ref/lib assets are supported')
    return assets, libraries


def stage(workspace, project, output, node_id, assets_file=None):
    assets, libraries = package_plan(workspace, project, assets_file)
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
        pilot = PILOT_PACKAGES.get(identity.lower())
        expected_restore_hash = pilot['restoreContentHash'] if pilot else sha512
        if expected_restore_hash != library['sha512']:
            raise ValueError('hash-mismatch: package archive disagrees with restore')
        if pilot and hashlib.sha256(raw).hexdigest() != pilot['archiveSha256']:
            raise ValueError('hash-mismatch: package archive differs from qualified pilot pin')
        files = []
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if entry.is_dir(): continue
                name = entry.filename
                if name.endswith('.nuspec'): name = name.lower()
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise ValueError('unsupported-package: escaping archive entry')
                analyzer_payload = (name.startswith('analyzers/dotnet/cs/') and
                    len(name.split('/')) == 4 and name.endswith('.dll'))
                if not analyzer_payload and name.split('/')[0].lower() in ('runtimes', 'native', 'analyzers', 'build', 'buildtransitive', 'buildmultitargeting', 'content', 'contentfiles', 'tools') and name.split('/')[0].lower() not in (pilot or {}).get('additionalRoots', []):
                    raise ValueError('unsupported-package: only managed ref/lib payloads supported')
                contents = package.read(entry)
                source = folder / name
                archive_metadata = name in ('_rels/.rels', '[Content_Types].xml') or name.startswith('package/services/metadata/core-properties/')
                if not source.is_file():
                    # NuGet omits OPC archive bookkeeping from the extracted cache.
                    if not (pilot and archive_metadata): raise ValueError('missing-input: ' + str(source))
                elif source.read_bytes() != contents:
                    raise ValueError('hash-mismatch: package payload ' + name)
                target = output / 'packages' / relative / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
                paths.append(target.relative_to(output).as_posix())
                files.append(dict(path=name, size=len(contents), sha256=hashlib.sha256(contents).hexdigest()))
        if pilot:
            name = archive.name
            target = output / 'packages' / relative / name
            target.write_bytes(raw)
            paths.append(target.relative_to(output).as_posix())
            files.append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
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
