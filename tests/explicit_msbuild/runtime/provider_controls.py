"""Check source runtime payload invalidation without recompiling managed projects."""
import argparse
import json
import os
from pathlib import Path
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace',type=Path)
p.add_argument('evidence',type=Path)
p.add_argument('--remote-cache')
a=p.parse_args()
a.evidence.mkdir(parents=True)
w=a.workspace.resolve(); evidence=a.evidence.resolve()
bazel=os.environ['RULES_MSBUILD_BAZEL']
version=subprocess.check_output([bazel,'--version'],text=True).strip()
assert version=='bazel '+os.environ['USE_BAZEL_VERSION'],version
marker=w/'runtime/runtime-state.txt'
original=marker.read_bytes()
records=[]

def run(case, failure=False, no_compile=False, executed=None):
    execution=evidence/(case+'.json')
    command=[bazel,'--batch','--output_base='+str(evidence/'base'),'test','//runtime:smoke',
             '--test_output=all','--jobs=2','--worker_max_instances=MSBuildAssembly=1',
             '--execution_log_json_file='+str(execution)]
    if a.remote_cache:command+=['--remote_cache='+a.remote_cache]
    result=subprocess.run(command,cwd=w,text=True,capture_output=True)
    (evidence/(case+'.log')).write_text(result.stdout+result.stderr)
    assert (result.returncode!=0)==failure,(case,result.stdout[-6000:]+result.stderr[-6000:])
    rows=[];text=execution.read_text().strip();decoder=json.JSONDecoder()
    while text:
        row,end=decoder.raw_decode(text);rows.append(row);text=text[end:].lstrip()
    compile=[r for r in rows if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit')]
    tests=[r for r in rows if r.get('mnemonic')=='TestRunner' and not r.get('cacheHit')]
    if no_compile:assert not compile,case
    if executed is not None:assert bool(tests)==executed,case
    records.append(dict(case=case,compilations=len(compile),testExecuted=bool(tests),exitCode=result.returncode))
    (evidence/'report.json').write_text(json.dumps(dict(bazel=version,cases=records),indent=2)+'\n')
    print(json.dumps(records[-1]),flush=True)

try:
    run('source-host')
    run('noop',no_compile=True,executed=False)
    marker.write_text('invalid')
    run('runtime-payload-edit',failure=True,no_compile=True,executed=True)
    marker.write_bytes(original)
    run('restored',no_compile=True)
finally:
    marker.write_bytes(original)
