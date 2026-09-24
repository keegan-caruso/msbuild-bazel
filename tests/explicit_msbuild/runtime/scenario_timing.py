"""Measure a fresh-output-base build, then cached and forced test execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from timing_tools import verify_tools

p=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','base','report']:p.add_argument(name,type=Path)
p.add_argument('--scenario',choices=['recovery','cold'],required=True)
p.add_argument('--cache')
p.add_argument('--expect',type=Path)
p.add_argument('--tests',action='store_true')
p.add_argument('--workers',type=int,default=1)
p.add_argument('--selection',type=Path,help='Raw configured roots, required with --managed-only')
p.add_argument('--managed-only',action='store_true',help='Build assembly reference output groups without host layouts or native products')
a=p.parse_args();w=a.workspace.resolve();base=a.base.resolve();out=a.report.resolve()
assert not base.exists(),'Use a new output base'
assert 1 <= a.workers <= 2, 'The comparison uses two Bazel jobs'
assert a.scenario!='recovery' or a.cache,'Recovery needs an HTTP cache'
assert not (a.managed_only and (a.tests or a.expect)), 'Managed-only is a separate build comparison'
out.mkdir(parents=True,exist_ok=False)
toolchain=verify_tools('9.2.0',cwd=out)
(out/'toolchain.json').write_text(json.dumps(toolchain,indent=2)+'\n')
manifest=json.loads((w/'subset.json').read_text());targets=[t['label'] for t in manifest['tests']]
if a.managed_only:
    assert a.selection, 'Use the same configured roots as the raw comparison'
    entries=json.loads(a.selection.read_text())['entries']
    targets=['//upstream:'+e['project'].removesuffix('.csproj').replace('/','_')+'_'+e['framework'] for e in entries]
start=[toolchain['bazelExecutable'],'--batch','--host_jvm_args=-Xmx1536m','--output_base='+str(base),'--ignore_all_rc_files']
flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly='+str(a.workers),'--disk_cache=','--remote_cache='+(a.cache if a.scenario=='recovery' else ''),'--remote_upload_local_results=false','--remote_download_outputs=all']
if a.managed_only:flags+=['--output_groups=reference']
records=[]

def execution_rows(path):
    decoder=json.JSONDecoder();data=''
    with path.open() as stream:
        while True:
            chunk=stream.read(1024*1024);data+=chunk
            while data.strip():
                data=data.lstrip()
                try:row,end=decoder.raw_decode(data)
                except json.JSONDecodeError:
                    if not chunk:raise
                    break
                yield row;data=data[end:]
            if not chunk:break

def run(case,verb,extra=()):
    command=start+[verb,*targets,*flags,*extra,'--execution_log_json_file='+str(out/(case+'.execution.json')),'--build_event_json_file='+str(out/(case+'.bep')),'--profile='+str(out/(case+'.profile.json.gz'))]
    begin=time.monotonic()
    with (out/(case+'.log')).open('w') as log:
        result=subprocess.run(command,cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=2400)
    wall=time.monotonic()-begin
    row=dict(case=case,wallSeconds=round(wall,3),exitCode=result.returncode,command=command)
    records.append(row)
    (out/'report.json').write_text(json.dumps(dict(scenario=a.scenario,managedOnly=a.managed_only,workers=a.workers,toolchain=toolchain,records=records),indent=2)+'\n')
    if result.returncode:raise RuntimeError(f'{case} failed ({result.returncode}); see {out / (case + ".log")}')
    counts={};row['compiled']=[]
    for action in execution_rows(out/(case+'.execution.json')):
        name=action['mnemonic']
        if name=='MSBuildAssembly':row['compiled'].append(dict(target=action['targetLabel'],cacheHit=bool(action.get('cacheHit'))))
        counts.setdefault(name,dict(total=0,cacheHits=0))
        counts[name]['total']+=1;counts[name]['cacheHits']+=bool(action.get('cacheHit'))
    row['actions']=counts
    events=[json.loads(line) for line in (out/(case+'.bep')).read_text().splitlines()]
    row['tests']=[{k:e['testResult'].get(k) for k in ['status','cachedLocally','executionInfo']} for e in events if 'testResult' in e]
    if a.scenario=='recovery':
        for name in ['MSBuildAssembly','RuntimeNative','MSBuildLayout']:
            count=counts.get(name,dict(total=0,cacheHits=0));assert count['total']==count['cacheHits'],(case,name,count)
    if case=='build':
        assert 'TestRunner' not in counts,'Build executed tests'
        if a.scenario=='recovery':
            assert counts['MSBuildAssembly']['total']
            if not a.managed_only:assert counts['RuntimeNative']['total']
        else:
            assert counts['MSBuildAssembly']['cacheHits']==0
            if not a.managed_only:assert counts['RuntimeNative']['cacheHits']==0
        if a.managed_only:
            assert not counts.get('RuntimeNative')
            # Contract layouts are compilation inputs; only the runtime-host
            # layout must be absent from a managed-only build.
            assert not any(action['mnemonic']=='MSBuildLayout' and action.get('targetLabel')=='//runtime:tree' for action in execution_rows(out/(case+'.execution.json')))
    if case=='cached-tests' and a.scenario=='recovery':
        assert len(row['tests'])==len(targets) and all(t.get('executionInfo',{}).get('cachedRemotely') for t in row['tests']),row['tests']
    if case=='forced-tests':assert counts['TestRunner']['total']==len(targets)
    (out/'report.json').write_text(json.dumps(dict(scenario=a.scenario,managedOnly=a.managed_only,workers=a.workers,toolchain=toolchain,records=records),indent=2)+'\n')
    print(dict(case=case,wallSeconds=row['wallSeconds'],actions=counts),flush=True)

run('build','build')
hashes={}
for path in sorted((w/'bazel-out').rglob('*')):
    if not path.is_file() or path.name.endswith('.params'):continue
    relative=path.relative_to(w/'bazel-out')
    if any(part.endswith(('.reference','.runtime','.layout','.generated')) for part in relative.parts):
        hashes[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
assert hashes
(out/'hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
if a.expect:assert hashes==json.loads(a.expect.read_text())['hashes'],'Recovered outputs differ from seed'
if a.tests:
    run('cached-tests' if a.scenario=='recovery' else 'tests','test')
    run('forced-tests','test',['--nocache_test_results'])
