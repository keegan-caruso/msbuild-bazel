"""API parity and observed invalidation controls for a prepared Primitives workspace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('control',type=Path);p.add_argument('output',type=Path);p.add_argument('--base',required=True);args=p.parse_args()
w=args.workspace.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];api=os.environ['RULES_MSBUILD_APICOMPAT']
lib='Microsoft.Extensions.Primitives';prefix='src_libraries_'+lib+'_';target='//upstream:'+prefix+'tests_'+lib+'.Tests_net10.0'
start=[bazel,'--host_jvm_args=-Xmx768m','--output_base='+args.base,'--ignore_all_rc_files'];flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1']
records=[]
def run(name,cmd,cwd=w,success=True):
    with (out/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=900,env=dict(os.environ,DOTNET_ROOT=str(sdk)))
    records.append(dict(case=name,exitCode=r.returncode));(out/'report.json').write_text(json.dumps(records,indent=2)+'\n')
    assert (r.returncode==0)==success,(name,r.returncode,out/(name+'.log'))
    print(name,r.returncode,flush=True)
def build(name):
    execution=out/(name+'.execution.json')
    run(name,start+['test',target,'//smoke','--execution_log_json_file='+str(execution)]+flags)
    data=execution.read_text();actions=[];decoder=json.JSONDecoder()
    while data.strip():
        row,end=decoder.raw_decode(data.lstrip());data=data.lstrip()[end:];actions.append(row)
    selected=[r['targetLabel'] for r in actions if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit')]
    records[-1]['compiled']=selected;records[-1]['testsExecuted']=sorted({r['targetLabel'] for r in actions if r.get('mnemonic')=='TestRunner' and not r.get('cacheHit')})
    return selected
reference=w/'bazel-bin/upstream'/(prefix+'ref_'+lib+'_net10.0.reference')/(lib+'.dll')
implementation=w/'bazel-bin/upstream'/(prefix+'src_'+lib+'_net10.0.runtime')/(lib+'.dll')
raw=args.control/'source/artifacts/bin'/lib
refs=next((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net10.0'))
def compare(name,left,right,strict=False,success=True):
    run(name,[api,'-l',left,'-r',right,'--lref',refs,'--rref',refs,'--enable-rule-attributes-must-match','--enable-rule-cannot-change-parameter-name']+(['--strict-mode'] if strict else []),success=success)
build('baseline')
compare('contract-implementation',reference,implementation)
compare('raw-bazel-contract',raw/'ref/Release/net10.0'/(lib+'.dll'),reference,True)
compare('raw-bazel-implementation',raw/'Release/net10.0'/(lib+'.dll'),implementation,True)
assert not build('noop')
assert records[-1]['testsExecuted']==[]
body=w/'upstream/src/libraries'/lib/'src/StringSegment.cs';original=body.read_text()
# A private method changes implementation bytes but leaves behavior/public contract intact.
needle='public readonly struct StringSegment'
assert needle in original
pos=original.index('{',original.index(needle))+1
changed=original[:pos]+'\n        private static int BazelQualificationBody() => 42;\n'+original[pos:]
before=hashlib.sha256(reference.read_bytes()).hexdigest()
try:
    body.write_text(changed)
    compiled=build('body-edit')
    assert compiled==['//upstream:'+prefix+'src_'+lib+'_net10.0'],compiled
    assert hashlib.sha256(reference.read_bytes()).hexdigest()==before
    assert set(records[-1]['testsExecuted'])=={target,'//smoke:smoke'},records[-1]
finally:body.write_text(original)
build('body-revert')
contract=w/'upstream/src/libraries'/lib/'ref'/(lib+'.cs');original_contract=contract.read_text()
assert 'public readonly partial struct StringSegment' in original_contract or 'public readonly struct StringSegment' in original_contract
pos=original_contract.index('{',original_contract.index('struct StringSegment'))+1
try:
    contract.write_text(original_contract[:pos]+'\n        public static int BazelQualificationApi() { throw null; }\n'+original_contract[pos:])
    compiled=build('contract-edit')
    assert '//smoke:smoke' in compiled and target in compiled,compiled
    compare('contract-drift-rejected',reference,implementation,success=False)
finally:contract.write_text(original_contract)
build('contract-revert')
# Runtime-only content is an execution input and must not invalidate compilation.
marker=w/'runtime/qualification.txt';buildfile=w/'runtime/BUILD.bazel';saved=buildfile.read_text()
try:
    marker.write_text('runtime identity control\n')
    buildfile.write_text(saved.replace('paths={','paths={"qualification.txt":"qualification.txt",'))
    assert not build('runtime-edit')
    assert set(records[-1]['testsExecuted'])=={target,'//smoke:smoke'},records[-1]
finally:buildfile.write_text(saved);marker.unlink()
build('runtime-revert')
# Shared test source and build-tool source are declared inputs as well.
for case,path,required in [
    ('shared-test-source','src/libraries/Common/tests/System/Threading/Tasks/TaskTimeoutExtensions.cs',{target}),
    ('linker-task-source','src/tools/illink/src/ILLink.Tasks/LinkTask.cs',{'//upstream:'+prefix+'src_'+lib+'_net10.0'}),
]:
    file=w/'upstream'/path;saved=file.read_text()
    try:
        file.write_text(saved+'\n// Qualification input edit.\n')
        compiled=build(case)
        assert required<=set(compiled),compiled
    finally:file.write_text(saved)
    build(case+'-revert')
(out/'report.json').write_text(json.dumps(records,indent=2)+'\n')
