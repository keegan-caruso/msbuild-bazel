"""Verify managed implementation invalidation and rejection of a wrong runtime identity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','base','report']:parser.add_argument(name,type=Path)
parser.add_argument('--cache',required=True)
parser.add_argument('--source',required=True)
parser.add_argument('--old',required=True)
parser.add_argument('--new',required=True)
parser.add_argument('--target',required=True)
parser.add_argument('--contract',required=True)
parser.add_argument('--recompiled-dependent',action='append',default=[],help='Exact additional implementation-reference consumers that must recompile')
a=parser.parse_args();w=a.workspace.resolve();a.report.mkdir(parents=True,exist_ok=False)
start=[os.environ['RULES_MSBUILD_BAZEL'],'--batch','--host_jvm_args=-Xmx1536m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files']
tests=[t['label'] for t in json.loads((w/'subset.json').read_text())['tests']]
records=[]
def run(name,success=True):
    execution=a.report/(name+'.execution.json')
    with (a.report/(name+'.log')).open('w') as log:
        p=subprocess.run(start+['test',*tests,'--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--remote_cache='+a.cache,'--disk_cache=','--test_output=errors','--execution_log_json_file='+str(execution)],cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    assert (p.returncode==0)==success,(name,a.report/(name+'.log'))
    text=execution.read_text();rows=[];decoder=json.JSONDecoder();offset=0
    while offset<len(text):
        if text[offset].isspace():offset+=1;continue
        row,offset=decoder.raw_decode(text,offset)
        rows.append({key:row.get(key) for key in ['mnemonic','targetLabel','cacheHit']})
    built=[r['targetLabel'] for r in rows if r.get('mnemonic') in ['RuntimeNative','MSBuildAssembly'] and not r.get('cacheHit')]
    executed=sorted({r['targetLabel'] for r in rows if r.get('mnemonic')=='TestRunner' and not r.get('cacheHit')})
    result={'case':name,'exitCode':p.returncode,'built':built,'testsExecuted':executed};records.append(result)
    (a.report/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(result,flush=True)
    return result
row=run('noop');assert not row['built'] and not row['testsExecuted'],row
wrapper=w/'runtime/host.sh';saved=wrapper.read_bytes()
try:
    wrapper.write_bytes(saved.replace(b'export DOTNET_ROOT=',b'export QUALIFICATION_CORELIB_SHA256='+b'0'*64+b'\nexport DOTNET_ROOT='))
    row=run('wrong-corelib',False);assert not row['built'] and len(row['testsExecuted'])==len(tests),row
    assert 'Qualification loaded wrong binary' in (a.report/'wrong-corelib.log').read_text()
finally:wrapper.write_bytes(saved)
row=run('restore-expectation');assert not row['built'],row
# Change one implementation body without changing the public contract.
source=w/'upstream'/a.source;saved=source.read_bytes()
package,target=a.target.removeprefix('//').split(':')
assembly=json.loads((w/'subset.json').read_text())['managed']
name=next(n for n,label in assembly.items() if label==a.target)
implementation=w/'bazel-bin'/package/(target+'.runtime')/name
contract_package,contract_target=a.contract.removeprefix('//').split(':')
reference=w/'bazel-bin'/contract_package/(contract_target+'.reference')/name
before=hashlib.sha256(implementation.read_bytes()).hexdigest()
contract=reference.read_bytes()
try:
    assert saved.count(a.old.encode())==1,(a.source,a.old)
    source.write_bytes(saved.replace(a.old.encode(),a.new.encode()))
    row=run('implementation-edit')
    assert sorted(row['built'])==sorted([a.target,*a.recompiled_dependent]) and len(row['testsExecuted'])==len(tests),row
    assert hashlib.sha256(implementation.read_bytes()).hexdigest()!=before
    assert reference.read_bytes()==contract,'Implementation edit changed public reference'
finally:source.write_bytes(saved)
row=run('restore-implementation');assert not row['built'],row
