"""Fail-closed eligibility for reference-only consumption of SDK project outputs."""
from pathlib import Path
from xml.etree import ElementTree as ET
from discovery_contract import check_xml
from graph_packages import package_plan


def validate(workspace, graph):
    """The first slice has no custom targets, packages, resources or ref metadata.

    Framework analyzers remain declared SDK inputs. Project/package generators and
    arbitrary tasks retain the existing full-implementation dependency protocol.
    """
    checked = set()
    depended = {identity for node in graph['nodes'] for identity in node['dependencies']}
    for node in graph['nodes']:
        _, libraries = package_plan(Path(workspace), node['project'].removeprefix('workspace/'), node['execution']['assetsFile'].removeprefix('workspace/'), node['targetFramework'])
        if libraries: raise ValueError('compile boundary requires package-free SDK projects')
        if set(node['globalProperties']) - {'configuration', 'targetframework'} or node['globalProperties'].get('configuration') != 'Release':
            raise ValueError('compile boundary requires the qualified Release configuration')
        if node['id'] in depended and node['outputType'] != 'Library':
            raise ValueError('executable project references require full bundles')
        if node['targetFramework'] != 'net10.0':
            raise ValueError('compile boundary requires net10.0')
        for item in node['inputs']:
            path, kind = item['path'], item['kind']
            if kind in ('package', 'content', 'resource', 'additional', 'extra', 'signing') or path.startswith('packages/'):
                raise ValueError('compile boundary requires package-free SDK projects')
            if kind == 'analyzer' and not path.startswith('dotnet/packs/Microsoft.NETCore.App.Ref/'):
                raise ValueError('implementation-consuming analyzer requires full dependency bundle')
            if kind not in ('project', 'import') or not path.startswith('workspace/'):
                continue
            local = Path(workspace) / path.removeprefix('workspace/')
            if local in checked: continue
            checked.add(local)
            check_xml(local)
            tree = ET.parse(local)
            for element in tree.iter():
                tag = element.tag.rsplit('}', 1)[-1]
                if tag in ('PackageReference', 'Reference', 'Content', 'EmbeddedResource', 'AdditionalFiles', 'BazelExtraInput'):
                    raise ValueError('unqualified compile boundary item: ' + tag)
                if tag == 'None' and set(element.attrib) - {'Include', 'Remove', 'Update', 'Condition'}:
                    raise ValueError('unqualified runtime content metadata')
