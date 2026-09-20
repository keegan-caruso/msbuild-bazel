"""Reject a same-size, same-mtime change to a privately staged package."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def run(a):
    a.output.mkdir(parents=True,exist_ok=False)
    request=json.loads(a.request.read_text())
    for key in ['output','apiOutput','runtimeOutput','diagnostics']:request[key]=str(a.output/key)
    request['validatePublication']=True
    path=a.output/'request.json';path.write_text(json.dumps(request))
    session=Path(request['output'])/'.work/session.json'
    with (a.output/'runner.log').open('w') as log:
        proc=subprocess.Popen([str(a.dotnet),str(a.runner),'--portable-request',str(path)],cwd=a.execroot,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+120
            while not session.exists():
                if proc.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Session not reached')
                time.sleep(.005)
            # Session creation can precede its final write; wait for complete JSON.
            while True:
                try:s=json.loads(session.read_text());break
                except json.JSONDecodeError:
                    if time.monotonic()>deadline:raise
                    time.sleep(.001)
            relative=next(f['path'] for f in s['files'] if f['path'].startswith('.nuget/packages/') and f['path'].endswith('.nupkg'))
            target=Path(s['workspace'])/relative;st=target.stat();os.chmod(target,st.st_mode|0o200)
            with target.open('r+b') as f:
                first=f.read(1);f.seek(0);f.write(bytes([first[0]^1]))
            os.utime(target,ns=(st.st_atime_ns,st.st_mtime_ns))
            code=proc.wait(timeout=120)
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
    action=json.loads((Path(request['diagnostics'])/'action.json').read_text())
    assert code!=0 and action['exitCode']!=0 and action['compiles']==0,'Staged corruption was not rejected before compilation'
    (a.output/'report.json').write_text(json.dumps(dict(exitCode=code,rejected=True,package=relative,sameSize=True,sameMtime=True),indent=2)+'\n')
    print('Staged package corruption rejected',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['request','execroot','output','dotnet','runner']:p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
