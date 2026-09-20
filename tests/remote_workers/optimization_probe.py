"""Paired baseline/candidate actions with exact same-path bundle comparison."""
import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def run(a):
    a.output.mkdir(parents=True,exist_ok=False)
    records=[];expected=None
    for index,mode in enumerate(["baseline","candidate","candidate","baseline","baseline","candidate"]):
        profile=True
        runner=a.baseline if mode=="baseline" else a.runner
        request=json.loads(a.request.read_text())
        for field in ['output','apiOutput','runtimeOutput','diagnostics']:
            request[field]=str(a.output/'action'/field)
            shutil.rmtree(request[field],ignore_errors=True)
        request.update(profileMsbuild=profile,validatePublication=True)
        path=a.output/'request.json';path.write_text(json.dumps(request))
        start=time.perf_counter()
        with (a.output/f'run-{index}.log').open('w') as log:
            proc=subprocess.run([str(a.dotnet),str(runner),'--portable-request',str(path)],cwd=a.execroot,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        elapsed=time.perf_counter()-start
        if proc.returncode:raise RuntimeError(f'run {index} failed')
        payload=Path(request['output'])
        hashes={str(p.relative_to(payload)):hashlib.sha256(p.read_bytes()).hexdigest() for p in payload.rglob('*') if p.is_file()}
        if expected is None:expected=hashes
        assert hashes==expected,'Profiling changed entry outputs'
        diag=a.output/f'diagnostics-{index}';shutil.copytree(request['diagnostics'],diag)
        record=dict(mode=mode,profile=profile,seconds=elapsed,identicalFiles=len(hashes),phases=json.loads((diag/'timings.json').read_text()))
        if profile:
            record['msbuild']=json.loads((diag/'msbuild-phases.json').read_text())
            record['plugin']=json.loads((diag/'msbuild-phases.json.plugin.json').read_text())
        records.append(record);(a.output/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(record),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['request','execroot','output','dotnet','runner','baseline']:p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
