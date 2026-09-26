"""Raw test parity, warm caching, body-edit invalidation and contract drift."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

workspace,base,raw,out=map(lambda p:Path(p).resolve(),sys.argv[1:5])
target,source,needle,replacement,assembly=sys.argv[5:10]
loaded_assembly=sys.argv[10] if len(sys.argv)>10 else ('System.IO.Pipelines' if 'Pipelines' in target else None)
replacement=replacement.replace("\\n", "\n")
out.mkdir(parents=True,exist_ok=False)
rules=Path(__file__).resolve().parents[3]
cmd=[os.environ.get('RULES_MSBUILD_BAZEL',str(rules/'scripts/bazel-launcher.sh')),'--output_base='+str(base),'--ignore_all_rc_files']
rows=[]
def run(name,args,success=True):
    p=subprocess.run(cmd+args,cwd=workspace,text=True,capture_output=True)
    (out/(name+'.log')).write_text(p.stdout+p.stderr)
    assert (p.returncode==0)==success,(name,(p.stdout+p.stderr)[-3000:])
    rows.append({'case':name,'exitCode':p.returncode});print(name,p.returncode,flush=True)
    return p.stdout+p.stderr
ns={'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
def results(path):return Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult',ns))
def test(name):
    run(name,['test',target,'--jobs=2','--test_output=errors','--build_event_json_file='+str(out/(name+'.bep'))])
    records=[json.loads(line) for line in (out/(name+'.bep')).read_text().splitlines()]
    tests=[e['testResult'] for e in records if 'testResult' in e];assert len(tests)==1
    proofs=list((workspace/'bazel-testlogs'/target.split(':')[1]/'test.outputs').glob('loaded-source-*.json'))
    if loaded_assembly:
        built=workspace/('bazel-bin/src_libraries_'+loaded_assembly+'_src_'+loaded_assembly+'_net10_0.runtime/'+loaded_assembly+'.dll')
        expected=hashlib.sha256(built.read_bytes()).hexdigest().upper()
        assert proofs and all(json.loads(p.read_text())['sha256']==expected for p in proofs)
        rows.append({'case':name+'-source-assembly','sha256':expected})
    return tests[0]
path=workspace/source;original=path.read_text();contract=workspace/'Directory.Build.targets';original_contract=contract.read_text()
try:
    test('baseline')
    target_name=target.split(':')[1]
    actual=results(workspace/'bazel-testlogs'/target_name/'test.outputs/results.trx')
    expected=results(raw)
    compare=lambda cases:cases
    if loaded_assembly == 'System.Collections.Immutable':
        sys.path.insert(0,str(rules/'tests/explicit_msbuild/runtime'))
        from case_names import normalized, shuffled
        compare=normalized
        rows.append({'case':'display-normalization','exactDisplayNamesMatch':actual==expected,'shuffledCases':sum(n for (name,_),n in actual.items() if name.split('(',1)[0] in shuffled)})
    assert compare(actual)==compare(expected),(compare(actual)-compare(expected),compare(expected)-compare(actual))
    rows.append({'case':'raw-parity','tests':sum(actual.values()),'outcomes':dict(Counter(outcome for (_,outcome),n in actual.items() for _ in range(n)))})
    assert test('warm').get('cachedLocally'), 'Test result not cached'
    ref=workspace/'bazel-bin'/(assembly+'.reference')
    digest=lambda:hashlib.sha256(next(ref.glob('*.dll')).read_bytes()).hexdigest()
    before=digest();assert needle in original
    path.write_text(original.replace(needle,replacement,1))
    assert not test('body-edit').get('cachedLocally',False),'Dependency edit did not rerun tests'
    assert digest()==before,'Body edit changed public contract'
    rows.append({'case':'body-edit-reference','unchanged':True})
    path.write_text(original);test('restored')
    contract.write_text(original_contract+'\n')
    diagnostic=run('contract-drift',['run','//:sync','--','--check'],False)
    assert 'contract changed' in diagnostic
finally:
    path.write_text(original);contract.write_text(original_contract)
    (out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
