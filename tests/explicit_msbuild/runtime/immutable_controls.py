"""Check body/API invalidation, strict API validation, and runtime-only invalidation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from immutable_edits import edit

workspace, base, folder, raw = map(lambda p:Path(p).resolve(),sys.argv[1:])
folder.mkdir(parents=True,exist_ok=False)
start=[os.environ['RULES_MSBUILD_BAZEL'],'--host_jvm_args=-Xmx768m','--output_base='+str(base),'--ignore_all_rc_files']
implementation='//upstream:src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10.0'
contract='//upstream:src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net10.0'
tests='//upstream:src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10.0'
records=[]
def run(case,error=None):
    execution=folder/(case+'.execution.json')
    with (folder/(case+'.log')).open('w') as log:
        result=subprocess.run(start+['test',tests,'//smoke','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--test_output=errors','--execution_log_json_file='+str(execution)],cwd=workspace,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    assert (result.returncode==0)==(error is None),(case,result.returncode)
    if error:assert error in (folder/(case+'.log')).read_text()
    data=execution.read_text();actions=[];decoder=json.JSONDecoder()
    while data.strip():
        row,end=decoder.raw_decode(data.lstrip());data=data.lstrip()[end:];actions.append(row)
    compiled=sorted({a['targetLabel'] for a in actions if a.get('mnemonic')=='MSBuildAssembly' and not a.get('cacheHit')})
    executed=sorted({a['targetLabel'] for a in actions if a.get('mnemonic')=='TestRunner' and not a.get('cacheHit')})
    item=dict(case=case,exitCode=result.returncode,compiled=compiled,executedTests=executed)
    records.append(item);(folder/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(item),flush=True)
    if not error:
        subprocess.run([sys.executable,Path(__file__).with_name('immutable_verify.py'),workspace,raw,folder/(case+'.parity.json')],check=True,stdout=subprocess.DEVNULL)
    return item

def digest():
    return hashlib.sha256((workspace/'bazel-bin/upstream'/ (implementation.split(':')[1]+'.runtime/System.Collections.Immutable.dll')).read_bytes()).hexdigest()
try:
    run('baseline');original=digest()
    r=run('noop');assert not r['compiled'] and not r['executedTests'],r
    with edit(workspace,'body'):
        r=run('body');assert r['compiled']==sorted([implementation,tests]),r
        assert r['executedTests']==sorted([tests,'//smoke:smoke']),r
        assert digest()!=original,'Body edit must survive trimming'
    run('body-recovery')
    with edit(workspace,'contract-only'):
        run('contract-only',error='CP0002')
    run('contract-recovery')
    with edit(workspace,'api'):
        r=run('api');assert set(r['compiled'])=={contract,implementation,tests,'//smoke:smoke'},r
        assert r['executedTests']==sorted([tests,'//smoke:smoke']),r
    run('api-recovery')
    # Point the load probe at the original installed DLL: running the rebuilt
    # assembly must now fail, without recompiling any assembly.
    host=workspace/'runtime/host.sh';original_wrapper=host.read_text()
    try:
        installed=next((workspace/'runtime/shared/Microsoft.NETCore.App').glob('*/System.Collections.Immutable.dll'))
        # Add a distinct declared file to the layout for the negative assertion.
        expected=workspace/'runtime/installed-immutable.dll';expected.write_bytes(installed.read_bytes())
        build=workspace/'runtime/BUILD.bazel';original_build=build.read_text()
        build.write_text(original_build.replace('paths={','paths={"installed-immutable.dll":"installed-immutable.dll",',1))
        host.write_text(original_wrapper.replace('/shared/Microsoft.NETCore.App/10.0.11/System.Collections.Immutable.dll','/installed-immutable.dll'))
        r=run('wrong-assembly-proof',error='Qualification loaded the wrong Immutable assembly')
        assert not r['compiled'] and r['executedTests']==sorted([tests,'//smoke:smoke']),r
    finally:
        host.write_text(original_wrapper);build.write_text(original_build);expected.unlink(missing_ok=True)
    run('runtime-recovery')
finally:subprocess.run(start+['shutdown'],cwd=workspace,check=True)
