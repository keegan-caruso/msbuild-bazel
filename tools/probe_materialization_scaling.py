"""Paired, byte-equivalent materialization measurements, without native builds."""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import types
import zipfile

import prepare_graph

BASELINE = '3bdb903e6c52c810d58fddfe355cf16b355ce8de'
ROOT = Path(__file__).resolve().parents[1]


def previous(name, revision):
    path = ROOT / 'tools' / (name + '.py')
    source = subprocess.check_output(['git', 'show', revision + ':tools/' + path.name], cwd=ROOT)
    module = types.ModuleType('baseline_' + name)
    module.__file__ = str(path)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def fixture(root, count, shape):
    root.mkdir(parents=True)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('lib/net10.0/Fixture.dll', b'package-fixture' * 4096)
    raw = archive.getvalue()
    folder = root / '.nuget/packages/fixture/1.0.0'
    (folder / 'lib/net10.0').mkdir(parents=True)
    (folder / 'fixture.1.0.0.nupkg').write_bytes(raw)
    (folder / 'lib/net10.0/Fixture.dll').write_bytes(b'package-fixture' * 4096)
    assets = dict(libraries={'Fixture/1.0.0':dict(type='package',path='fixture/1.0.0',sha512=base64.b64encode(hashlib.sha512(raw).digest()).decode())},
        targets={'net10.0':{'Fixture/1.0.0':{}}},project={'frameworks':{'net10.0':{'dependencies':{}}}})
    (root / 'Directory.Build.props').write_text('<Project/>')
    nodes=[]
    for n in range(count):
        name=f'P{n:04d}';directory=root/name;(directory/'obj').mkdir(parents=True)
        (directory/(name+'.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"/>')
        (directory/'Value.cs').write_text('class '+name+' {}')
        (directory/'obj/project.assets.json').write_text(json.dumps(assets))
        (directory/'obj/project.nuget.cache').write_text(json.dumps(dict(dgSpecHash='fixture',success=True)))
        edges=([n-1] if n else []) if shape=='chain' else list(range(max(0,n//2*2-2),n//2*2))
        nodes.append(dict(id=f'{n:024x}',project=f'workspace/{name}/{name}.csproj',targetFramework='net10.0',
            globalProperties={'configuration':'Release','targetframework':'net10.0'},dependencies=[f'{i:024x}' for i in edges],
            inputs=[dict(kind=kind,path='workspace/'+path) for kind,path in [('project',f'{name}/{name}.csproj'),('source',f'{name}/Value.cs'),('import','Directory.Build.props')]]))
    return dict(toolchain={'sdkVersion':'10.0.400'},nodes=nodes,entryPoints=[nodes[-1]['id']])


def inventory(root):
    return {p.relative_to(root).as_posix():dict(mode=p.stat().st_mode & 0o777,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(root.rglob('*')) if p.is_file()}


def probe(output, sizes, shapes, repetitions, baseline):
    output.mkdir(parents=True,exist_ok=False)
    old=previous('prepare_graph',baseline);old.graph_packages=previous('graph_packages',baseline)
    report=dict(accepted=False,scope='materialization only; no native evaluation/build',baseline=baseline,
        candidate=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        candidateCode={p:hashlib.sha256((ROOT/'tools'/p).read_bytes()).hexdigest() for p in ('prepare_graph.py','graph_packages.py')},
        repetitions=repetitions,threshold=dict(minReduction=.1,minSecondsSaved=.1),workloads={})
    def save():(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for count in sizes:
            for shape in shapes:
                name=f'{shape}-{count}';source=output/name/'source';graph=fixture(source,count,shape)
                record=dict(samples=[],equivalent=True);report['workloads'][name]=record
                expected=None
                for repetition in range(repetitions+1):
                    for variant in (('baseline','candidate') if repetition%2 else ('candidate','baseline')):
                        module=old if variant=='baseline' else prepare_graph
                        target=output/name/'generated';target.mkdir();(target/'restore').mkdir()
                        started=time.perf_counter()
                        module.write_build(source,graph,target)
                        seconds=time.perf_counter()-started
                        actual=inventory(target)
                        if expected is None:expected=actual
                        assert actual==expected,'materialization differs: '+name+' '+variant
                        record['samples'].append(dict(repetition=repetition,warmup=repetition==0,variant=variant,seconds=seconds))
                        shutil.rmtree(target);save()
                        print(name,variant,repetition,round(seconds,3),flush=True)
                record['outputInventorySha256']=hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
                record['files']=len(expected)
                record['summary']={variant:dict(median=statistics.median(values),minimum=min(values),maximum=max(values))
                    for variant in ('baseline','candidate') if (values:=[s['seconds'] for s in record['samples'] if s['variant']==variant and not s['warmup']])}
                before=record['summary']['baseline']['median'];after=record['summary']['candidate']['median']
                record.update(reduction=1-after/before,secondsSaved=before-after,meaningful=1-after/before>=.1 and before-after>=.1)
                save()
        report['accepted']=True
    finally:save()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sizes',type=int,nargs='+',default=[100,1000])
    parser.add_argument('--shapes',nargs='+',choices=['chain','fan'],default=['chain','fan'])
    parser.add_argument('--repetitions',type=int,default=5)
    parser.add_argument('--baseline',default=BASELINE)
    args=parser.parse_args()
    probe(args.output,args.sizes,args.shapes,args.repetitions,args.baseline)
