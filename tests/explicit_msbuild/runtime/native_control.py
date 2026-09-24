"""Build the pinned raw native control and record tool/output identities.

Run in the qualified Ubuntu 22.04 ARM64 container after installing the native
prerequisites listed in the upstream linux-requirements.md. Acquisition is setup.
"""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
source, output = [Path(p).resolve() for p in sys.argv[1:]]
output.mkdir(parents=True,exist_ok=False)
assert platform.system()=='Linux' and platform.machine()=='aarch64'
commit='60629d14374c56f1cb51819049ad1fa529307f8d'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit
assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
command=['./src/coreclr/build-runtime.sh','-arm64','-release','-component','runtime','-component','jit','-component','hosts','-numproc','6']
start=time.monotonic()
with (output/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=source,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
folder=source/'artifacts/bin/coreclr/linux.arm64.Release'
report={'commit':commit,'command':command,'seconds':round(time.monotonic()-start,3),'exitCode':result.returncode,'outputs':{}}
if result.returncode==0:
    for name in ['libcoreclr.so','libclrjit.so','corerun']:
        path=folder/name
        report['outputs'][name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
report['packages']=subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\n'],text=True).splitlines()
(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
result.check_returncode()
