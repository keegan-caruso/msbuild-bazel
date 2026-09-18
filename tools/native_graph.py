"""Opt-in native-cache preparation through the existing evaluated graph boundary."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from preparation_identity import digest
from prepare_graph import prepare

POLICY = 'evaluated-api-runtime-v2'


def relative(value):
    if not value.startswith('workspace/'):
        raise ValueError('native graph requires workspace paths')
    result=value[len('workspace/'):]
    if not result or Path(result).is_absolute() or any(p in ('', '.', '..') for p in result.split('/')):
        raise ValueError('unsafe native graph path')
    return result


def qualify(graph):
    nodes={n['id']:n for n in graph['nodes']}
    if len(nodes)!=len(graph['nodes']) or not nodes or len(graph['entryPoints'])!=1:
        raise ValueError('native graph requires one entry and unique nodes')
    projects=set()
    for n in nodes.values():
        project=relative(n['project']);folder=Path(project).parent
        if project in projects or n['globalProperties']!={'configuration':'Release','targetframework':'net10.0'}:
            raise ValueError('native graph requires unique Release/net10 projects')
        projects.add(project)
        expected=str(folder/'bin/Release/net10.0')
        if (n['targetFramework']!='net10.0' or n['outputType'] not in ('Library','Exe') or
            relative(n['execution']['outputDirectory'])!=expected or
            relative(n['execution']['referenceDirectory'])!=str(folder/'obj/Release/net10.0/ref') or
            n['outputs']!=[dict(kind='assembly',path='workspace/'+expected+'/'+Path(project).stem+'.dll')]):
            raise ValueError('unqualified native output layout')
        if any(dep not in nodes for dep in n['dependencies']):raise ValueError('missing native graph dependency')
    if graph['entryPoints'][0] not in nodes:raise ValueError('missing native graph entry')
    return nodes


def materialize(prepared, graph, output, toolchain):
    """Consume only a private plan returned by prepare(), never an unchecked export."""
    nodes=qualify(graph)
    output.mkdir()
    shutil.copytree(prepared/'src',output/'src')
    packages=prepared/'packages'
    # Retain declared NuGet metadata; verified archive payloads replace package imports.
    if packages.exists():shutil.copytree(packages,output/'src/.nuget/packages',dirs_exist_ok=True)
    restore={}
    projects={}
    records={}
    for identity,n in nodes.items():
        state=json.loads((prepared/'restore'/f'{identity}.json').read_text())
        # Only the SDK Build handoff. Restore-only receipts contain path-salted hashes.
        selected={p:v for p,v in state.items() if Path(p).name=='project.assets.json' or p.endswith(('.nuget.g.props','.nuget.g.targets'))}
        restore.update(selected)
        package_manifest=json.loads((prepared/'package-manifests'/f'{identity}.json').read_text())
        for package in package_manifest['packages']:
            for f in package['files']:
                data=(packages/package['path']/f['path']).read_bytes()
                if len(data)!=f['size'] or hashlib.sha256(data).hexdigest()!=f['sha256']:
                    raise ValueError('package manifest payload changed')
        inputs={}
        for item in n['inputs']:
            logical=item['path']
            if item['kind']=='package':
                inputs[logical]=item['sha256']
            elif logical.startswith('workspace/'):
                path=relative(logical)
                if '/obj/' not in path:
                    data=(output/'src'/path).read_bytes()
                    inputs[logical]=hashlib.sha256(data).hexdigest()
            else:inputs[logical]=item['sha256']
        # Global controls are part of every node's evaluated environment.
        for name in ('global.json','NuGet.Config','NuGet.config','Directory.Build.props','Directory.Build.targets'):
            path=output/'src'/name
            if path.is_file():inputs['workspace/'+name]=hashlib.sha256(path.read_bytes()).hexdigest()
        records[relative(n['project'])]=dict(policy=POLICY,inputs=inputs,restore=selected,packages=package_manifest,configuration=n['globalProperties'],graphInputs=graph.get('graphInputs',[]))
        projects[relative(n['project'])]=dict(identity=digest(records[relative(n['project'])]),dependencies=[relative(nodes[d]['project']) for d in n['dependencies']])
    manifest=dict(policy=POLICY,toolchain=toolchain,projects=projects)
    (output/'identity-records.json').write_text(json.dumps(records,sort_keys=True)+'\n')
    (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    (output/'restore.json').write_text(json.dumps(restore,sort_keys=True)+'\n')
    (output/'entry.json').write_text(json.dumps(dict(entry=relative(nodes[graph['entryPoints'][0]]['project'])))+'\n')
    shutil.copytree(prepared/'package-manifests',output/'package-manifests')
    (output/'graph.json').write_text(json.dumps(graph,indent=2)+'\n')
    return manifest



def refresh_sources(previous, workspace, graph, output, toolchain, *, certificate, previous_certificate, payload_sha256):
    """Reuse a verified native payload for a qualified compile-content-only change.

    The caller holds discovery/preparation leases. Re-derive the narrow graph
    update here, verify copied bytes, and replace only the named C# inputs and
    their project identities. Package archives/restore/imports cannot change.
    """
    from preparation_reuse import payload_identity
    from preparation_source_update import refresh
    old_graph = json.loads((previous / 'graph.json').read_text())
    derived = refresh(previous_certificate, old_graph, certificate['identity'])
    if derived is None or derived != (graph, certificate):
        raise ValueError('native source refresh is not a qualified derivation')
    qualify(graph)
    shutil.copytree(previous, output)
    if payload_identity(output) != payload_sha256:
        raise ValueError('native payload changed during source refresh')
    manifest = json.loads((output / 'manifest.json').read_text())
    records = json.loads((output / 'identity-records.json').read_text())
    if manifest['toolchain'] != toolchain or set(records) != set(manifest['projects']):
        raise ValueError('native refresh identity mismatch')
    for project, record in records.items():
        if digest(record) != manifest['projects'][project]['identity']:
            raise ValueError('native refresh record mismatch')
    changed = set(certificate['derivation']['changedSources'])
    inputs = graph.get('graphInputs', []) + [item for node in graph['nodes'] for item in node['inputs']]
    hashes = {item['path']: item['sha256'] for item in inputs if item['path'] in changed}
    for logical in changed:
        path = relative(logical)
        data = (workspace / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != hashes[logical]:
            raise ValueError('native source changed during refresh')
        (output / 'src' / path).write_bytes(data)
    for project, record in records.items():
        record['inputs'].update({path: value for path, value in hashes.items() if path in record['inputs']})
        record['graphInputs'] = graph.get('graphInputs', [])
        manifest['projects'][project]['identity'] = digest(record)
    (output / 'identity-records.json').write_text(json.dumps(records, sort_keys=True) + '\n')
    (output / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
    (output / 'graph.json').write_text(json.dumps(graph, indent=2) + '\n')
    return manifest


def prepare_native(workspace, graph_path, output, *, toolchain, environment=None, _prebuilt_tools=None):
    workspace,graph_path,output=map(lambda p:Path(p).resolve(),(workspace,graph_path,output))
    if len(toolchain)!=64 or any(c not in '0123456789abcdef' for c in toolchain):raise ValueError('explicit toolchain digest required')
    if output.exists():raise FileExistsError(output)
    qualify(json.loads(graph_path.read_text()))
    with tempfile.TemporaryDirectory(prefix='.native-plan-',dir=output.parent) as temp:
        root=Path(temp);validated=root/'validated'
        graph=prepare(workspace,graph_path,validated,environment=environment,_prebuilt_tools=_prebuilt_tools)
        result=materialize(validated,graph,root/'payload',toolchain)
        (root/'payload').rename(output)
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('workspace','graph','output','toolchain'):p.add_argument('--'+name,required=True)
    a=p.parse_args();prepare_native(a.workspace,a.graph,a.output,toolchain=a.toolchain)
