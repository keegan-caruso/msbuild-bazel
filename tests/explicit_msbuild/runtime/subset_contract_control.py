"""A forwarded contract still rejects an API absent from its implementation."""
import argparse
import json
import os
from pathlib import Path
import subprocess

p=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','base','report']:p.add_argument(name,type=Path)
p.add_argument('--cache',required=True)
a=p.parse_args();w=a.workspace.resolve();a.report.mkdir(parents=True,exist_ok=False)
target='//upstream:src_libraries_System.Runtime.Serialization.Formatters_src_System.Runtime.Serialization.Formatters_net10.0'
source=w/'upstream/src/libraries/System.Runtime.Serialization.Formatters/ref/System.Runtime.Serialization.Formatters.cs'
records=[]
def run(name,error=None):
    log=a.report/(name+'.log')
    with log.open('w') as output:
        result=subprocess.run([os.environ['RULES_MSBUILD_BAZEL'],'--batch','--host_jvm_args=-Xmx1536m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files','build',target,'--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--remote_cache='+a.cache],cwd=w,stdout=output,stderr=subprocess.STDOUT,timeout=600)
    text=log.read_text();assert (result.returncode==0)==(error is None),(name,text[-6000:])
    if error:assert 'CP0002' in text and error in text,(name,text[-6000:])
    records.append(dict(case=name,exitCode=result.returncode,expectedMissingMember=error));(a.report/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(records[-1],flush=True)
run('baseline')
saved=source.read_bytes();old=b'protected Formatter() { }';assert saved.count(old)==1
try:
    source.write_bytes(saved.replace(old,old+b'\n        public abstract void QualificationMissingMember();'))
    run('missing-contract-api','QualificationMissingMember')
finally:source.write_bytes(saved)
run('restore-contract')
