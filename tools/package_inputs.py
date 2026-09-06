"""Deterministic, checksum-pinned build-package preparation for the fixture."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/package-inputs'
PACKAGE_ID = 'Spike.BuildInputs'


def archive_bytes(version):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for source in sorted((FIXTURE / version).rglob('*')):
            if source.is_file():
                info = zipfile.ZipInfo(source.relative_to(FIXTURE / version).as_posix(), (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, source.read_bytes())
    return output.getvalue()


def feed(directory):
    directory.mkdir(parents=True)
    pins = json.loads((FIXTURE / 'pins.json').read_text())
    for version, expected in pins.items():
        contents = archive_bytes(version)
        if hashlib.sha256(contents).hexdigest() != expected:
            raise ValueError('package archive pin mismatch: ' + version)
        (directory / f'{PACKAGE_ID}.{version}.nupkg').write_bytes(contents)
    return pins


def configure(workspace, version, package_feed):
    project = workspace / 'Shared/Shared.csproj'
    tree = ET.parse(project)
    refs = tree.getroot().findall('.//PackageReference')
    if refs:
        refs[0].set('Version', f'[{version}]')
    else:
        ET.SubElement(ET.SubElement(tree.getroot(), 'ItemGroup'), 'PackageReference',
                      Include=PACKAGE_ID, Version=f'[{version}]')
        source = next((workspace / 'Shared').glob('*.cs'))
        source.write_text(source.read_text().replace('"shared-v1"', '"shared-v1" + "/" + PackageInput.Value'))
    tree.write(project)
    config = ET.parse(workspace / 'NuGet.Config')
    sources = config.getroot().find('packageSources')
    for item in list(sources):
        if item.get('key') == 'spike-local':
            sources.remove(item)
    ET.SubElement(sources, 'add', key='spike-local', value=str(package_feed))
    config.write(workspace / 'NuGet.Config')


def stage(prepare, workspace, pins, archives=None):
    """Stage verified payloads and an archive-derived NuGet installation marker."""
    shutil.rmtree(workspace / 'packages', ignore_errors=True)
    (workspace / 'packages').mkdir()
    (workspace / 'package-manifests').mkdir(exist_ok=True)
    for project in ('Shared', 'App'):
        assets = json.loads((prepare / project / 'obj/project.assets.json').read_text())
        packages = []
        for identity, library in sorted(assets['libraries'].items()):
            if library['type'] != 'package':
                continue
            package_id, version = identity.split('/')
            key = identity if archives is not None else version
            if (archives is None and package_id != PACKAGE_ID) or key not in pins:
                raise ValueError('unsupported unpinned package: ' + identity)
            contents = archives[identity] if archives is not None else archive_bytes(version)
            if hashlib.sha256(contents).hexdigest() != pins[key]:
                raise ValueError('package archive pin mismatch')
            package_path = f'{package_id.lower()}/{version}'
            if library['path'] != package_path:
                raise ValueError('unexpected package path')
            restored_archive = prepare / '.nuget/packages' / package_path / f'{package_id.lower()}.{version}.nupkg'
            if not restored_archive.is_file() or hashlib.sha256(restored_archive.read_bytes()).hexdigest() != pins[key]:
                raise ValueError('restored package archive differs from pin: ' + identity)
            files = []
            with zipfile.ZipFile(io.BytesIO(contents)) as archive:
                for name in archive.namelist():
                    restored = prepare / '.nuget/packages' / package_path / name
                    expected = archive.read(name)
                    # NuGet lowercases the nuspec filename in the global cache.
                    if name.endswith('.nuspec'):
                        restored = restored.with_name(restored.name.lower())
                        name = name.lower()
                    if not restored.is_file() or restored.read_bytes() != expected:
                        raise ValueError('restored package payload differs from pin: ' + name)
                    target = workspace / 'packages' / package_path / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(expected)
                    files.append(dict(path=name, sha256=hashlib.sha256(expected).hexdigest(), size=len(expected)))
            # ResolvePackageAssets recognizes an installed package by its
            # .nupkg.sha512 sidecar (or .nupkg.metadata), not DLL presence alone.
            # Derive this from verified archive bytes; never copy ambient cache metadata.
            archive_hash = base64.b64encode(hashlib.sha512(contents).digest()).decode('ascii')
            if library['sha512'] != archive_hash:
                raise ValueError('restored package content hash differs from archive: ' + identity)
            name = f'{package_id.lower()}.{version}.nupkg.sha512'
            marker = archive_hash.encode('ascii')
            (workspace / 'packages' / package_path / name).write_bytes(marker)
            files.append(dict(path=name, sha256=hashlib.sha256(marker).hexdigest(), size=len(marker)))
            packages.append(dict(id=package_id, version=version, path=package_path,
                                 archiveSha256=pins[key], files=files))
        (workspace / 'package-manifests' / (project + '.json')).write_text(
            json.dumps(dict(schemaVersion=1, packages=packages), indent=2))
