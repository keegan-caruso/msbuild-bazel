"""HTTP seed/recovery gate; invoke in independent Linux containers with fresh bases."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('base',type=Path);p.add_argument('report',type=Path);p.add_argument('--cache',required=True);p.add_argument('--seed',action='store_true');p.add_argument('--case',choices=['baseline','body','api'],default='baseline');p.add_argument('--expect',type=Path);a=p.parse_args()
w=a.workspace.resolve();a.report.parent.mkdir(parents=True,exist_ok=True)
lib='Microsoft.Extensions.Primitives';prefix='src_libraries_'+lib+'_';test='//upstream:'+prefix+'tests_'+lib+'.Tests_net10.0'
body=w/'upstream/src/libraries'/lib/'src/StringSegment.cs';contract=w/'upstream/src/libraries'/lib/'ref'/(lib+'.cs');originals={f:f.read_text() for f in [body,contract]}
if a.case!='baseline':
    for f in ([body] if a.case=='body' else [body,contract]):
        s=originals[f];pos=s.index('{',s.index('struct StringSegment'))+1
        declaration='private static int BazelQualificationBody() => 42;' if a.case=='body' else '/// <summary>Qualification API edit.</summary>\n        public static int BazelQualificationApi() '+('{ throw null; }' if f==contract else '=> 42;')
        f.write_text(s[:pos]+'\n        '+declaration+'\n'+s[pos:])
start=[os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx768m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files']
flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--remote_cache='+a.cache,'--remote_upload_local_results='+str(a.seed).lower(),'--remote_download_outputs=all']
def run(name,extra=[]):
    execution=a.report.with_suffix('.'+name+'.execution.json');bep=a.report.with_suffix('.'+name+'.bep')
    with a.report.with_suffix('.'+name+'.log').open('w') as log:r=subprocess.run(start+['test',test,'//smoke','--execution_log_json_file='+str(execution),'--build_event_json_file='+str(bep)]+flags+extra,cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    assert r.returncode==0,a.report.with_suffix('.'+name+'.log')
    data=execution.read_text();actions=[];decoder=json.JSONDecoder()
    while data.strip():
        row,end=decoder.raw_decode(data.lstrip());data=data.lstrip()[end:];actions.append(row)
    return actions,[json.loads(l) for l in bep.read_text().splitlines()]
try:
    actions,events=run('recover')
    assembly=[x for x in actions if x.get('mnemonic')=='MSBuildAssembly']
    if not a.seed:
        assert assembly and all(x.get('cacheHit') for x in assembly),[(x['targetLabel'],x.get('cacheHit')) for x in assembly]
        results=[e['testResult'] for e in events if 'testResult' in e]
        assert len(results)==2 and all(r.get('executionInfo',{}).get('cachedRemotely') for r in results),results
    hashes={}
    for label in (w/'all-targets.txt').read_text().splitlines()+['//smoke:smoke']:
        package,name=label.removeprefix('//').split(':');folder=w/'bazel-bin'/package
        for suffix in ['.reference','.runtime']:
            for path in sorted((folder/(name+suffix)).rglob('*')):
                if path.is_file() and not path.name.endswith('.params'):hashes[package+'/'+str(path.relative_to(folder))]=hashlib.sha256(path.read_bytes()).hexdigest()
    if a.expect:assert hashes==json.loads(a.expect.read_text())['hashes'],'Recovered outputs differ'
    if not a.seed:
        forced,_=run('execute',['--nocache_test_results'])
        assert not any(x.get('mnemonic')=='MSBuildAssembly' and not x.get('cacheHit') for x in forced)
        assert {x['targetLabel'] for x in forced if x.get('mnemonic')=='TestRunner'}=={test,'//smoke:smoke'}
    a.report.write_text(json.dumps(dict(case=a.case,seed=a.seed,assemblyActions=len(assembly),assemblyCacheHits=sum(bool(x.get('cacheHit')) for x in assembly),cachedTests=not a.seed,forcedExecutionPassed=not a.seed,hashes=hashes),indent=2)+'\n')
    print(a.case,'assemblies',len(assembly),'cache hits',sum(bool(x.get('cacheHit')) for x in assembly),'files',len(hashes),flush=True)
finally:
    for f,s in originals.items():f.write_text(s)
    subprocess.run(start+['shutdown'],cwd=w,check=True)
