"""Opt-in native-cache preparation through the existing evaluated graph boundary."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from preparation_identity import digest
from prepare_graph import prepare

POLICY = 'evaluated-packages-v1'


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
        projects[relative(n['project'])]=dict(identity=digest(dict(policy=POLICY,inputs=inputs,restore=selected,packages=package_manifest,configuration=n['globalProperties'],graphInputs=graph.get('graphInputs',[]))),dependencies=[relative(nodes[d]['project']) for d in n['dependencies']])
    manifest=dict(policy=POLICY,toolchain=toolchain,projects=projects)
    (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    (output/'restore.json').write_text(json.dumps(restore,sort_keys=True)+'\n')
    (output/'entry.json').write_text(json.dumps(dict(entry=relative(nodes[graph['entryPoints'][0]]['project'])))+'\n')
    shutil.copytree(prepared/'package-manifests',output/'package-manifests')
    (output/'graph.json').write_text(json.dumps(graph,indent=2)+'\n')
    return manifest


def prepare_native(workspace, graph_path, output, *, toolchain):
    workspace,graph_path,output=map(lambda p:Path(p).resolve(),(workspace,graph_path,output))
    if len(toolchain)!=64 or any(c not in '0123456789abcdef' for c in toolchain):raise ValueError('explicit toolchain digest required')
    if output.exists():raise FileExistsError(output)
    qualify(json.loads(graph_path.read_text()))
    with tempfile.TemporaryDirectory(prefix='.native-plan-',dir=output.parent) as temp:
        root=Path(temp);validated=root/'validated'
        graph=prepare(workspace,graph_path,validated)
        result=materialize(validated,graph,root/'payload',toolchain)
        (root/'payload').rename(output)
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('workspace','graph','output','toolchain'):p.add_argument('--'+name,required=True)
    a=p.parse_args();prepare_native(a.workspace,a.graph,a.output,toolchain=a.toolchain)
