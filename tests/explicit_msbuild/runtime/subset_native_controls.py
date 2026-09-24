"""Verify one native product invalidates all selected runtime consumers."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

parser=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','base','report']:parser.add_argument(name,type=Path)
parser.add_argument('--cache',required=True)
parser.add_argument('--native-package',required=True)
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
# Upstream copy_version_files preserves a non-placeholder version file. This
# also gives a bounded native-only edit that changes the runtime's identity.
archive=w/a.native_package/'source.tar';backup=archive.with_suffix('.control-save');archive.rename(backup)
try:
    with tarfile.open(backup) as src,tarfile.open(archive,'w') as dest:
        for entry in src:
            if entry.name=='artifacts/obj/_version.c':
                data=src.extractfile(entry).read().replace(b'Version N/A',b'Version 10.0.0').replace(b'@Commit:',b'@QualificationEdit: @Commit:')
                entry.size=len(data);dest.addfile(entry,io.BytesIO(data))
            else:dest.addfile(entry,src.extractfile(entry) if entry.isfile() else None)
    row=run('native-version-edit');assert row['built']==['//'+a.native_package+':runtime'] and len(row['testsExecuted'])==len(tests),row
finally:
    archive.unlink(missing_ok=True);backup.rename(archive)
row=run('restore-native');assert not row['built'],row
