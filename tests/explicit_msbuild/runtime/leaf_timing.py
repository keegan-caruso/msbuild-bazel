"""Time build-only Pipelines body edits across the qualified runtime target set."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from benchmarks.measure import command as timed_command
import re
import statistics
import subprocess
import uuid

from timing_tools import verify_tools

p=argparse.ArgumentParser(description=__doc__)
for n in ['workspace','base','report']:p.add_argument(n,type=Path)
p.add_argument('--cache',required=True)
p.add_argument('--repetitions',type=int,default=3)
p.add_argument('--expected-bazel',default='9.2.0')
a=p.parse_args();assert a.repetitions>=3
w=a.workspace.resolve();out=a.report.resolve();out.mkdir(parents=True,exist_ok=False)
(out/'toolchain.json').write_text(json.dumps(verify_tools(a.expected_bazel,cwd=out),indent=2)+'\n')
manifest=json.loads((w/'subset.json').read_text());targets=[t['label'] for t in manifest['tests']]
target=manifest['managed']['System.IO.Pipelines.dll']
name=target.split(':')[1];contract=name.replace('_src_','_ref_')
source=w/'upstream/src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'
saved=source.read_bytes();old=b'UseSynchronizationContext = useSynchronizationContext;';assert saved.count(old)==1
nonce=uuid.uuid4().hex;records=[]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(mode,case):
    prefix=[os.environ['RULES_MSBUILD_BAZEL']]+(['--batch'] if mode=='batch' else [])+['--host_jvm_args=-Xmx1536m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files']
    stem=out/(mode+'-'+case);execution=stem.with_suffix('.execution.json')
    command=prefix+['build',*targets,'--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--remote_cache='+a.cache,'--remote_upload_local_results=false','--remote_download_outputs=all','--disk_cache=','--execution_log_json_file='+str(execution),'--profile='+str(stem.with_suffix('.profile.json.gz'))]
    result,wall=timed_command(command,w,stem.with_suffix('.log'),timeout=600)
    assert result.returncode==0,(case,stem.with_suffix('.log'))
    log=stem.with_suffix('.log').read_text();match=re.search(r'Elapsed time: ([0-9.]+)s, Critical Path: ([0-9.]+)s',log);assert match
    data=execution.read_text();decoder=json.JSONDecoder();offset=0;actions=[]
    while offset<len(data):
        if data[offset].isspace():offset+=1;continue
        row,offset=decoder.raw_decode(data,offset)
        actions.append({k:row.get(k) for k in ['mnemonic','targetLabel','cacheHit']})
    compiled=[r['targetLabel'] for r in actions if r['mnemonic'] in ['MSBuildAssembly','RuntimeNative'] and not r['cacheHit']]
    assert not any(r['mnemonic']=='TestRunner' for r in actions),'Build-only run executed tests'
    row=dict(mode=mode,case=case,wallSeconds=round(wall,3),bazelSeconds=float(match[1]),criticalPathSeconds=float(match[2]),compiled=compiled,actions=actions,command=command)
    records.append(row);(out/'report.json').write_text(json.dumps(dict(nonce=nonce,target=target,records=records),indent=2)+'\n')
    print({k:v for k,v in row.items() if k not in ['actions','command']},flush=True)
    return row
try:
    for mode in ['batch','server']:
        row=run(mode,'prime');assert not row['compiled'],row
        implementation=w/'bazel-bin/upstream'/(name+'.runtime/System.IO.Pipelines.dll')
        reference=w/'bazel-bin/upstream'/(contract+'.reference/System.IO.Pipelines.dll')
        original=digest(implementation);public=digest(reference)
        for i in range(a.repetitions):
            row=run(mode,'noop-'+str(i));assert not row['compiled'],row
            body=old+(' GC.KeepAlive("leaf-timing-'+nonce+'-'+mode+'-'+str(i)+'");').encode()
            source.write_bytes(saved.replace(old,body))
            row=run(mode,'edit-'+str(i));assert row['compiled']==[target],row
            assert digest(reference)==public,'Public contract changed'
            assert digest(implementation)!=original,'Implementation output unchanged'
        source.write_bytes(saved)
        row=run(mode,'restore');assert not row['compiled'] and digest(implementation)==original and digest(reference)==public,row
finally:
    source.write_bytes(saved)
    # A container PID 1 may leave the exited Bazel server as an unreaped zombie.
    # Bound cleanup separately from the completed measurements.
    try:
        subprocess.run([os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx1536m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files','shutdown'],cwd=w,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT,timeout=15)
    except subprocess.TimeoutExpired:
        print('Bazel shutdown timed out; stop the qualification container after saving evidence.',flush=True)
summary={mode:{kind:{'wallMedianSeconds':statistics.median(r['wallSeconds'] for r in records if r['mode']==mode and r['case'].startswith(kind+'-')),'bazelMedianSeconds':statistics.median(r['bazelSeconds'] for r in records if r['mode']==mode and r['case'].startswith(kind+'-'))} for kind in ['noop','edit']} for mode in ['batch','server']}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
