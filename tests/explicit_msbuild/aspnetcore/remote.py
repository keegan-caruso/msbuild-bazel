"""Seed or independently consume the large ASP.NET Core HTTP action cache."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('workspace',type=Path);parser.add_argument('base',type=Path);parser.add_argument('report',type=Path)
parser.add_argument('--jobs',type=int,default=32)
parser.add_argument('--inspect-only',action='store_true');parser.add_argument('--cache',required=True);parser.add_argument('--seed',action='store_true')
args=parser.parse_args();workspace=args.workspace.resolve();base=args.base.resolve();report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True)
startup=[os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx1024m','--output_base='+str(base),'--ignore_all_rc_files']
command=startup+['build','//upstream:benchmark','--jobs='+str(args.jobs),'--local_resources=cpu=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=2','--disk_cache=','--remote_cache='+args.cache,'--remote_upload_local_results='+str(args.seed).lower(),'--remote_download_outputs=all','--build_event_json_file='+str(report.with_suffix('.bep'))]
try:
    seconds=None
    if args.inspect_only:
        assert 'Build completed successfully' in report.with_suffix('.log').read_text()
    else:
        start=time.perf_counter()
        with report.with_suffix('.log').open('w') as log:result=subprocess.run(command,cwd=workspace,stdout=log,stderr=subprocess.STDOUT)
        seconds=time.perf_counter()-start
        assert result.returncode==0,report.with_suffix('.log')
    with report.with_suffix('.bep').open() as events:
        metrics=next(event['buildMetrics'] for event in map(json.loads,events) if 'buildMetrics' in event)
    counts={row['mnemonic']:int(row.get('actionsExecuted',0)) for row in metrics['actionSummary']['actionData']}
    runners={row['name']:row['count'] for row in metrics['actionSummary']['runnerCount']}
    assemblies=counts.get('MSBuildAssembly',0)
    assert assemblies==278 and counts.get('MSBuildNugetExtract')==300,counts
    if not args.seed:
        assert runners.get('remote cache hit')==578 and not runners.get('worker') and not runners.get('linux-sandbox'),runners
    hits=assemblies-runners.get('worker',0)
    tree=base/'execroot/_main/bazel-out/aarch64-fastbuild/bin/upstream';hashes={}
    for label in (workspace/'all-targets.txt').read_text().splitlines():
        name=label.split(':',1)[1]
        # Reference is one declared file, not a directory artifact. Bazel may
        # materialize an execution-only parameter file alongside it locally.
        request=json.loads((tree/(name+'.request.json')).read_text())
        reference=tree/(name+'.reference')/(request['assembly']+'.dll')
        hashes[str(reference.relative_to(tree))]=hashlib.sha256(reference.read_bytes()).hexdigest()
        for path in sorted((tree/(name+'.runtime')).rglob('*')):
            if path.is_file():hashes[str(path.relative_to(tree))]=hashlib.sha256(path.read_bytes()).hexdigest()
        path=tree/(name+'.restore-project.json');hashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    report.write_text(json.dumps(dict(seconds=seconds,assemblyActions=assemblies,assemblyCacheHits=hits,hashes=hashes),indent=2)+'\n')
    print('seconds',seconds,'assembly actions',assemblies,'cache hits',hits,'verified files',len(hashes),flush=True)
finally:
    if not args.inspect_only:subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
