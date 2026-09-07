"""Prepare managed reference/runtime package fixtures outside Bazel actions."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

import package_inputs

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/binary-packages'


def archive(project, package_id, version, dependency=None):
    root = ET.Element('package')
    metadata = ET.SubElement(root, 'metadata')
    for key, value in dict(id=package_id, version=version, authors='Adapter',
                           description='Managed binary boundary fixture').items():
        ET.SubElement(metadata, key).text = value
    if dependency:
        group = ET.SubElement(ET.SubElement(metadata, 'dependencies'), 'group', targetFramework='net10.0')
        ET.SubElement(group, 'dependency', id='RulesMsbuild.Leaf', version=f'[{dependency}]')
    files = {
        package_id + '.nuspec': ET.tostring(root),
        f'lib/net10.0/{package_id}.dll': (project / f'bin/Release/net10.0/{package_id}.dll').read_bytes(),
        f'ref/net10.0/{package_id}.dll': (project / f'obj/Release/net10.0/ref/{package_id}.dll').read_bytes(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as package:
        for name, contents in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            package.writestr(info, contents)
    return output.getvalue()


class Packages:
    def __init__(self, directory, dotnet, run):
        self.archives = {}
        for version, binary_value, leaf_value, leaf_version in (
                ('1.0.0', 'v1', 'v1', '1.0.0'),
                ('1.0.1', 'v2', 'v1', '1.0.0'),
                ('1.0.2', 'v2', 'v2', '1.0.1')):
            source = directory / version
            shutil.copytree(FIXTURE, source)
            # Avoid traversal acquisition and parent checkout MSBuild imports.
            (source / 'NuGet.Config').write_text('<configuration><packageSources><clear /></packageSources></configuration>')
            for name, value in (('Binary', binary_value), ('Leaf', leaf_value)):
                path = source / name / 'Value.cs'
                path.write_text(path.read_text().replace('-v1', '-' + value))
            run('binary-fixture-' + version, [dotnet, 'build', source / 'Binary/Binary.csproj',
                '-c', 'Release', '--nologo', '-p:EnableSourceControlManagerQueries=false',
                '-p:EnableSourceLink=false', '-p:Deterministic=true',
                f'-p:PathMap={source}=/_/package-fixture'], source)
            for name, selected, dependency in (('Leaf', leaf_version, None), ('Binary', version, leaf_version)):
                identity = f'RulesMsbuild.{name}/{selected}'
                contents = archive(source / name, 'RulesMsbuild.' + name, selected, dependency)
                if identity in self.archives and self.archives[identity] != contents:
                    raise ValueError('binary package preparation is not deterministic: ' + identity)
                self.archives[identity] = contents
        shutil.rmtree(directory)

    def feed(self, directory):
        directory.mkdir(parents=True)
        pins = {}
        for identity, contents in self.archives.items():
            package_id, version = identity.split('/')
            (directory / f'{package_id}.{version}.nupkg').write_bytes(contents)
            pins[identity] = hashlib.sha256(contents).hexdigest()
        return pins

    def configure(self, workspace, version, package_feed):
        project = workspace / 'Shared/Shared.csproj'
        tree = ET.parse(project)
        reference = tree.getroot().find('.//PackageReference')
        if reference is None:
            reference = ET.SubElement(ET.SubElement(tree.getroot(), 'ItemGroup'),
                                      'PackageReference', Include='RulesMsbuild.Binary')
            source = next((workspace / 'Shared').glob('*.cs'))
            source.write_text(source.read_text().replace('"shared-v1"',
                '"shared-v1/" + RulesMsbuild.Binary.Value.Read()'))
        reference.set('Version', f'[{version}]')
        tree.write(project)
        config = ET.parse(workspace / 'NuGet.Config')
        sources = config.getroot().find('packageSources')
        for item in list(sources):
            if item.get('key') == 'rules-msbuild-local':
                sources.remove(item)
        ET.SubElement(sources, 'add', key='rules-msbuild-local', value=str(package_feed))
        config.write(workspace / 'NuGet.Config')

    def stage(self, preparation, workspace, pins):
        package_inputs.stage(preparation, workspace, pins, self.archives)


def evidence(workspace, binary):
    deps = json.loads(binary.with_suffix('.deps.json').read_text())
    manifest = json.loads((workspace / 'package-manifests/App.json').read_text())
    files = {}
    for package in manifest['packages']:
        name = package['id'] + '.dll'
        payload = workspace / 'packages' / package['path']
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        files[name] = dict(outputSha256=digest(binary.with_name(name)),
                           runtimeSha256=digest(payload / 'lib/net10.0' / name),
                           referenceSha256=digest(payload / 'ref/net10.0' / name))
    return dict(identities=sorted(key for key, value in deps['libraries'].items()
                                  if value['type'] == 'package'), files=files)
