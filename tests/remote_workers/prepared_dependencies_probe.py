"""Compare direct prepared dependencies with full staging on retained project actions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    requests=[json.loads(p.read_text()) for p in (args.execroot/'bazel-out/darwin_arm64-fastbuild/bin').glob('project_*.request.json')]
    selected=sorted(requests,key=lambda r:r['entry'])[::max(1,len(requests)//args.projects)][:args.projects]
    entry=next(r for r in requests if r['entry'].endswith('OrchardCore.Cms.Web.csproj'))
    if entry not in selected:selected.append(entry)
    expected={};rows=[]
    for batch,direct in enumerate([False,True,True,False]):
        for index,original in enumerate(selected):
            request=dict(original, directDependencies=direct, profileMsbuild=True, validatePublication=True)
            for field in ['output','apiOutput','runtimeOutput','diagnostics']:
                path=args.output/'actions'/str(index)/field
                shutil.rmtree(path,ignore_errors=True);request[field]=str(path)
            path=args.output/'request.json';path.write_text(json.dumps(request))
            begin=time.perf_counter()
            p=subprocess.run([str(args.dotnet),str(args.runner),'--portable-request',str(path)],cwd=args.execroot,capture_output=True,text=True,timeout=300)
            seconds=time.perf_counter()-begin
            (args.output/f'{batch}-{index}.log').write_text(p.stdout+p.stderr)
            diagnostics=Path(request['diagnostics'])
            shutil.copytree(diagnostics,args.output/f'{batch}-{index}-diagnostics')
            assert p.returncode==0,(batch,original['entry'],p.stderr[-2500:])
            hashes={field+'/'+str(p.relative_to(request[field])):hashlib.sha256(p.read_bytes()).hexdigest()
                    for field in ['output','apiOutput','runtimeOutput'] for p in Path(request[field]).rglob('*') if p.is_file()}
            if index not in expected:expected[index]=hashes
            differences=[k for k in set(hashes)|set(expected[index]) if hashes.get(k)!=expected[index].get(k)]
            row=dict(batch=batch,direct=direct,project=original['entry'],seconds=seconds,files=len(hashes),differences=differences,
                     placement=json.loads((diagnostics/'dependency-inputs.json').read_text()),
                     phases=json.loads((diagnostics/'timings.json').read_text()),
                     msbuild=json.loads((diagnostics/'msbuild-phases.json').read_text()))
            rows.append(row);(args.output/'report.json').write_text(json.dumps(rows,indent=2))
            print(batch,index,original['entry'],round(seconds,3),row['placement'],'differences',len(differences),flush=True)
            assert not differences,(original['entry'],differences[:10])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['execroot','output','dotnet','runner']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--projects',type=int,default=2)
    run(p.parse_args())
