"""Prove the declared native archive boundary before compiling CoreCLR."""
import io
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tarfile

workspace, report = map(lambda s:Path(s).resolve(),sys.argv[1:])
report.mkdir(parents=True,exist_ok=False)
manifest=workspace/'native/products.json'
products=list(json.loads(manifest.read_text())['products'].values()) if manifest.exists() else ['libcoreclr.so','libclrjit.so','corerun']
library_name=next(name for name in products if name.endswith('.so'))
archive=workspace/'native/source.tar'
saved=archive.with_suffix('.saved');archive.rename(saved)
records=[]
start=[os.environ['RULES_MSBUILD_BAZEL'],'--batch','--host_jvm_args=-Xmx768m','--output_base='+str(report/'base'),'--ignore_all_rc_files']
def source(value,missing=False):
    with tarfile.open(archive,'w') as tar:
        files={'build-native.sh':'''set -euo pipefail
# Host checkout and SDK are absent, and networking has its own namespace.
test ! -e /work/runtime
test ! -e /opt/rules_msbuild-toolchain
mkdir result
'''+ 'cc -shared -fPIC fixture.c -o result/'+shlex.quote(library_name)+'\n'+''.join('cp '+('result/'+shlex.quote(library_name) if name.endswith('.so') else '/bin/true')+' result/'+shlex.quote(name)+'\n' for name in products if name!=library_name)+'tar --sort=name --mtime=@0 --owner=0 --group=0 -cf result.tar -C result .\n','fixture.c':'#include "value.h"\nint fixture_value(void) { return VALUE; }\n'}
        if not missing:files['value.h']='#define VALUE '+str(value)+'\n'
        for name,text in files.items():
            data=text.encode();entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o644;tar.addfile(entry,io.BytesIO(data))
def run(name,success=True,value=7):
    log=report/(name+'.execution.json')
    with (report/(name+'.log')).open('w') as stream:
        p=subprocess.run(start+['build','//native:runtime','--jobs=2','--strategy=MSBuildAssembly=worker','--strategy=MSBuildGenerate=worker','--worker_max_instances=MSBuildAssembly=1','--worker_max_instances=MSBuildGenerate=1','--disk_cache='+str(report/'cache'),'--execution_log_json_file='+str(log)],cwd=workspace,stdout=stream,stderr=subprocess.STDOUT,timeout=240)
    assert (p.returncode==0)==success,(name,(report/(name+'.log')).read_text()[-5000:])
    rows=[];text=log.read_text();decoder=json.JSONDecoder()
    while text.strip():
        row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:];rows.append(row)
    ran=[r['targetLabel'] for r in rows if r.get('mnemonic')=='RuntimeNative' and not r.get('cacheHit')]
    if success:
        library=workspace/'bazel-bin/native/runtime.generated'/library_name
        actual=int(subprocess.check_output([sys.executable,'-c','import ctypes,sys; print(ctypes.CDLL(sys.argv[1]).fixture_value())',str(library)],text=True))
        assert actual==value,(name,actual,value)
    record={'value':value if success else None,'case':name,'exitCode':p.returncode,'generationExecuted':ran};records.append(record)
    (report/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(record,flush=True)
    return ran
try:
    source(7);assert run('baseline')==['//native:runtime']
    assert run('noop')==[]
    source(8);assert run('header-change',value=8)==['//native:runtime']
    source(7);assert run('restore-from-cache')==[]
    source(7,missing=True);run('missing-header',False)
    source(9);assert run('retry-after-failure',value=9)==['//native:runtime']
finally:
    archive.unlink(missing_ok=True);saved.rename(archive)
