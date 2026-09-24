"""Seed or recover Immutable through HTTP in independent Linux containers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from immutable_edits import edit

parser=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','base','report','raw']:parser.add_argument(name,type=Path)
parser.add_argument('--cache',required=True)
parser.add_argument('--seed',action='store_true')
parser.add_argument('--case',choices=['baseline','body','api'],default='baseline')
parser.add_argument('--expect',type=Path)
a=parser.parse_args();w=a.workspace.resolve();a.report.parent.mkdir(parents=True,exist_ok=True)
start=[os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx768m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files']
test='//upstream:src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10.0'
flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--remote_cache='+a.cache,'--remote_upload_local_results='+str(a.seed).lower(),'--remote_download_outputs=all']
def run(name,extra=()):
    execution=a.report.with_suffix('.'+name+'.execution.json');bep=a.report.with_suffix('.'+name+'.bep')
    with a.report.with_suffix('.'+name+'.log').open('w') as log:
        result=subprocess.run(start+['test',test,'//smoke','--execution_log_json_file='+str(execution),'--build_event_json_file='+str(bep),*flags,*extra],cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    assert result.returncode==0,a.report.with_suffix('.'+name+'.log')
    data=execution.read_text();actions=[];decoder=json.JSONDecoder()
    while data.strip():
        row,end=decoder.raw_decode(data.lstrip());data=data.lstrip()[end:];actions.append(row)
    return actions,[json.loads(line) for line in bep.read_text().splitlines()]
try:
    with edit(w,a.case):
        actions,events=run('recover')
        assembly=[row for row in actions if row.get('mnemonic')=='MSBuildAssembly']
        layouts=[row for row in actions if row.get('mnemonic')=='MSBuildLayout']
        if not a.seed:
            assert assembly and all(row.get('cacheHit') for row in assembly),[(r['targetLabel'],r.get('cacheHit')) for r in assembly]
            assert layouts and all(row.get('cacheHit') for row in layouts)
            results=[e['testResult'] for e in events if 'testResult' in e]
            assert len(results)==2 and all(r.get('executionInfo',{}).get('cachedRemotely') for r in results),results
        hashes={}
        # Include tool-configured assemblies and their closures as well as the
        # target-configured outputs, reference-pack layouts and declared host.
        outputs=w/'bazel-out'
        for path in sorted(outputs.rglob('*')):
            if not path.is_file() or path.name.endswith('.params'):continue
            relative=path.relative_to(outputs)
            if any(part.endswith(('.reference','.runtime','.layout')) for part in relative.parts):
                hashes[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
        assert hashes
        if a.expect:assert hashes==json.loads(a.expect.read_text())['hashes'],'Recovered outputs differ'
        if not a.seed:
            forced,_=run('execute',['--nocache_test_results'])
            assert not any(r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit') for r in forced)
            assert {r['targetLabel'] for r in forced if r.get('mnemonic')=='TestRunner'}=={test,'//smoke:smoke'}
        subprocess.run([sys.executable,Path(__file__).with_name('immutable_verify.py'),w,a.raw,a.report.with_suffix('.parity.json')],stdout=subprocess.DEVNULL,check=True)
        a.report.write_text(json.dumps(dict(case=a.case,seed=a.seed,assemblyActions=len(assembly),assemblyCacheHits=sum(bool(r.get('cacheHit')) for r in assembly),layoutActions=len(layouts),layoutCacheHits=sum(bool(r.get('cacheHit')) for r in layouts),cachedTests=not a.seed,forcedExecutionPassed=not a.seed,hashes=hashes),indent=2)+'\n')
        print(a.case,'assemblies',len(assembly),'cache hits',sum(bool(r.get('cacheHit')) for r in assembly),'files',len(hashes),flush=True)
finally:subprocess.run(start+['shutdown'],cwd=w,check=True)
