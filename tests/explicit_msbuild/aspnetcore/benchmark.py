"""Serial raw/Bazel clean-output, no-op and shared-library body-edit timings.

Run after source preparation, restore, and compatibility validation. Both use two
build slots; tools/download caches are warm. No remote action cache is used here.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from spawn_log import actions

source, workspace, base, baseline, output = map(lambda p: Path(p).resolve(), sys.argv[1:6])
output.mkdir(parents=True,exist_ok=True)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL']
raw=[sdk/'dotnet','msbuild',baseline/'Workload.proj','-m:2','-v:minimal','-p:WarningsNotAsErrors=CS8629%3BIDE0031']
startup=[bazel,'--host_jvm_args=-Xmx1024m','--output_base='+str(base),'--ignore_all_rc_files']
flags=['--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=2','--jobs=2','--disk_cache=','--remote_cache=','--remote_download_outputs=all','--noexecution_log_sort']
bazel_only = sys.argv[6:] == ['--bazel-only']
assert not sys.argv[6:] or bazel_only
rows = [row for row in json.loads((output/'timings.json').read_text()) if row['case'].startswith('raw-')] if bazel_only else []
def run(case,command,cwd):
    start=time.perf_counter()
    with (output/(case+'.log')).open('w') as log: result=subprocess.run(list(map(str,command)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT)
    row=dict(case=case,seconds=time.perf_counter()-start,exitCode=result.returncode)
    rows.append(row);(output/'timings.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
    assert result.returncode==0,case
    return row

def build_raw(case):return run(case,raw+['-t:Build','-bl:'+str(output/(case+'.binlog'))],source)
def build_bazel(case):
    logging=[] if case=='bazel-clean-output' else ['--execution_log_json_file='+str(output/(case+'.execution.json'))]
    row=run(case,startup+['build','//upstream:benchmark']+logging+flags,workspace)
    if not logging: return row
    executed=[];cached=[]
    for action in actions(output/(case+'.execution.json')):
        if action.get('mnemonic')=='MSBuildAssembly':(cached if action.get('cacheHit') else executed).append(action.get('listedOutputs',[]))
    row.update(assemblyActionsExecuted=len(executed),assemblyActionCacheHits=len(cached),executedOutputs=executed)
    (output/'timings.json').write_text(json.dumps(rows,indent=2)+'\n')
    return row
relative='src/ObjectPool/src/DefaultObjectPool.cs'
original=(source/relative).read_bytes()
changed=original.replace(b'Environment.ProcessorCount * 2',b'Environment.ProcessorCount * 3')
assert changed!=original and original==(workspace/'upstream'/relative).read_bytes()
try:
    if not bazel_only:
        run('raw-clean',raw+['-t:Clean'],source)
        build_raw('raw-clean-output')
        for i in range(3):build_raw('raw-noop-'+str(i))
        (source/relative).write_bytes(changed);build_raw('raw-body-edit')
        (source/relative).write_bytes(original);build_raw('raw-revert')
        subprocess.run([sdk/'dotnet','build-server','shutdown'],check=True,stdout=subprocess.DEVNULL)
    run('bazel-clean',startup+['clean'],workspace)
    build_bazel('bazel-clean-output')
    for i in range(3):build_bazel('bazel-noop-'+str(i))
    references=list((base/'execroot/_main/bazel-out/aarch64-fastbuild/bin/upstream').glob('Microsoft.Extensions.ObjectPool_*.reference/*.dll'))
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in references}
    (workspace/'upstream'/relative).write_bytes(changed);edited=build_bazel('bazel-body-edit')
    assert before and all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in before.items()), 'Body edit changed reference bytes'
    assert edited['assemblyActionsExecuted']==len(references),(edited,len(references))
    (workspace/'upstream'/relative).write_bytes(original);build_bazel('bazel-revert')
finally:
    (source/relative).write_bytes(original);(workspace/'upstream'/relative).write_bytes(original)
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
