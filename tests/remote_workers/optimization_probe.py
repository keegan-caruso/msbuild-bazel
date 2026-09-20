"""Paired baseline/candidate actions with exact same-path bundle comparison."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def logical_hashes(payload, request, execroot):
    hashes={str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.rglob('*') if p.is_file()}
    directories={row['package']:execroot/row['source'] for row in request.get('packageDirectories',[])}
    for path in payload.rglob('package-origins.json'):
        bundle=path.parent;seal=bundle/'bundle.json'
        if not seal.exists() or json.loads(seal.read_text())['schemaVersion']!=3:continue
        origins=json.loads(path.read_text());artifacts={row['path']:row for row in json.loads((bundle/'artifacts.json').read_text())}
        for artifact,origin in origins.items():
            package,version,relative=origin.split('/',2);source=directories[package+'/'+version]/relative
            data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
            assert digest==artifacts[artifact]['sha256'] and len(data)==artifacts[artifact]['size']
            hashes[str((bundle/'artifacts'/artifact).relative_to(payload))]=digest
        del hashes[str(path.relative_to(payload))]
        original=json.loads(seal.read_text())
        dense=dict(schemaVersion=1,resultsSha256=original['resultsSha256'],artifactsSha256=original['artifactsSha256'])
        hashes[str(seal.relative_to(payload))]=hashlib.sha256((json.dumps(dense,indent=2)+'\n').encode()).hexdigest()
    return hashes


def run(a):
    a.output.mkdir(parents=True,exist_ok=False)
    sparse=None
    if a.package_origin_outputs:
        base=json.loads(a.request.read_text())
        sparse={str((a.execroot/p).resolve()):str(a.output/'sparse-inputs'/str(i)) for i,p in enumerate(base['prebuilt'])}
        payload=json.loads((a.execroot/base['preparedPlan']/'payload.json').read_text())
        hashes={k[len('.nuget/packages/'):]:v for k,v in payload.items() if k.startswith('.nuget/packages/')}
        mapping=a.output/'sparse-map.json';mapping.write_text(json.dumps(sparse))
        hashfile=a.output/'package-hashes.json';hashfile.write_text(json.dumps(hashes))
        subprocess.run([str(a.dotnet),str(a.test_helper),'--compact-package-bundles',str(mapping),str(hashfile)],check=True)
        # Keep unchanged dependency inputs at the exact baseline paths.
        sparse={source:destination if json.loads((Path(destination)/'bundle.json').read_text())['schemaVersion']==3 else source for source,destination in sparse.items()}
    records=[];expected=None
    for index,mode in enumerate(["baseline","candidate","candidate","baseline","baseline","candidate"]):
        profile=True
        runner=a.baseline if mode=="baseline" else a.runner
        request=json.loads(a.request.read_text())
        for field in ['output','apiOutput','runtimeOutput','diagnostics']:
            request[field]=str(a.output/'action'/field)
            shutil.rmtree(request[field],ignore_errors=True)
        request.update(profileMsbuild=profile,validatePublication=True)
        if a.borrow_package_inputs:request["borrowPackageInputs"]=mode=="candidate"
        if a.package_origin_outputs and mode=="candidate":
            request["packageOriginOutputs"]=True
            request["prebuilt"]=list(sparse.values())
        path=a.output/'request.json';path.write_text(json.dumps(request))
        start=time.perf_counter()
        with (a.output/f'run-{index}.log').open('w') as log:
            proc=subprocess.run([str(a.dotnet),str(runner),'--portable-request',str(path)],cwd=a.execroot,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        elapsed=time.perf_counter()-start
        if proc.returncode:raise RuntimeError(f'run {index} failed')
        payload=Path(request['output'])
        hashes={}
        for field in ['output','apiOutput','runtimeOutput']:
            hashes.update({field+'/'+k:v for k,v in logical_hashes(Path(request[field]),request,a.execroot).items()})
        if expected is None:expected=hashes
        assert hashes==expected,'Profiling changed entry outputs'
        diag=a.output/f'diagnostics-{index}';shutil.copytree(request['diagnostics'],diag)
        record=dict(mode=mode,profile=profile,seconds=elapsed,identicalFiles=len(hashes),phases=json.loads((diag/'timings.json').read_text()))
        if profile:
            record['msbuild']=json.loads((diag/'msbuild-phases.json').read_text())
            record['plugin']=json.loads((diag/'msbuild-phases.json.plugin.json').read_text())
        record['staging']=json.loads((diag/'staging.json').read_text())
        origin_report=diag/'package-origins.json'
        if origin_report.exists():record['packageOrigins']=json.loads(origin_report.read_text())
        records.append(record);(a.output/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(record),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['request','execroot','output','dotnet','runner','baseline']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--package-origin-outputs',action='store_true')
    p.add_argument('--borrow-package-inputs',action='store_true')
    p.add_argument('--test-helper',type=Path)
    run(p.parse_args())
