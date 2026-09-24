"""Measure retained compiler memory during unique leaf edits; restore source on exit.

Linux-only qualification, not a hard memory limit. Bazel's optional total-worker
limit evicts idle workers. Compare elapsed builds and process replacement as well
as RSS/PSS; shared pages make aggregate RSS an overestimate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from timing_tools import verify_tools

p=argparse.ArgumentParser(description=__doc__)
for name in ['workspace','selection','base','report']:p.add_argument(name,type=Path)
p.add_argument('--iterations',type=int,default=30)
p.add_argument('--memory-limit-mb',type=int,default=0)
p.add_argument('--shrink-pool',action='store_true')
p.add_argument('--minimum-available-mb',type=int,default=1536)
p.add_argument('--trim',action='store_true',help='Run Linux fstrim / outside build timing (requires permission)')
a=p.parse_args()
if a.iterations < 1 or a.memory_limit_mb < 0 or a.minimum_available_mb < 0:
    p.error('iterations must be positive and memory limits nonnegative')
a.base=a.base.resolve()
w=a.workspace.resolve();out=a.report.resolve();out.mkdir(parents=True,exist_ok=False)
tools=verify_tools('9.2.0',cwd=out)
entries=json.loads(a.selection.read_text())['entries']
targets=['//upstream:'+e['project'].removesuffix('.csproj').replace('/','_')+'_'+e['framework'] for e in entries]
command=[tools['bazelExecutable'],'--host_jvm_args=-Xmx1536m','--output_base='+str(a.base.resolve()),'--ignore_all_rc_files','build',*targets,'--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=2','--output_groups=reference','--disk_cache=','--remote_cache=','--experimental_total_worker_memory_limit_mb='+str(a.memory_limit_mb),'--experimental_worker_metrics_poll_interval=1s']
if a.shrink_pool:command.append('--experimental_shrink_worker_pool')
source=w/'upstream/src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'
reference=w/'bazel-bin/upstream/src_libraries_System.IO.Pipelines_ref_System.IO.Pipelines_net10.0.reference/System.IO.Pipelines.dll'
implementation=w/'bazel-bin/upstream/src_libraries_System.IO.Pipelines_src_System.IO.Pipelines_net10.0.runtime/System.IO.Pipelines.dll'
saved=source.read_bytes();old=b'UseSynchronizationContext = useSynchronizationContext;';assert saved.count(old)==1
rows=[];report=dict(toolchain=tools,command=command,iterationsRequested=a.iterations,rows=rows)
report['filesystemTrimOutsideTiming']=a.trim
nonce=uuid.uuid4().hex

def memory():
    processes=[]
    server=int((a.base/'server/server.pid.txt').read_text())
    parents={}
    for status in Path('/proc').glob('[0-9]*/status'):
        try:parents[int(status.parent.name)]=int(next(l for l in status.read_text().splitlines() if l.startswith('PPid:')).split()[1])
        except (FileNotFoundError,ProcessLookupError):pass
    def owned(pid):
        seen=set()
        while pid not in seen and pid in parents:
            if pid==server:return True
            seen.add(pid);pid=parents[pid]
        return False
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if not owned(int(proc.name)):continue
            args=(proc/'cmdline').read_bytes().split(b'\0')
            if not any(s.endswith(b'/VBCSCompiler.dll') for s in args):continue
            values={line.split(':')[0]:int(line.split()[1]) for line in (proc/'smaps_rollup').read_text().splitlines() if line.startswith(('Rss:','Pss:'))}
            processes.append(dict(pid=int(proc.name),**values))
        except (FileNotFoundError,ProcessLookupError):pass
    available=int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')).split()[1])
    return dict(processes=processes,rssMiB=sum(p['Rss'] for p in processes)/1024,pssMiB=sum(p['Pss'] for p in processes)/1024,availableMiB=available/1024)

def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def build(name):
    start=time.monotonic()
    with (out/(name+'.log')).open('w') as log:r=subprocess.run(command,cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=600)
    row=dict(case=name,seconds=time.monotonic()-start,exitCode=r.returncode,immediate=memory());rows.append(row);save();r.check_returncode()
    if a.trim:subprocess.run(['fstrim','/'],check=True)
    time.sleep(2) # Untimed observation window; lifecycle polling runs during builds.
    row['idle']=memory();save();print(json.dumps({k:row[k] for k in ['case','seconds']}|{'rssMiB':row['idle']['rssMiB'],'pssMiB':row['idle']['pssMiB'],'processes':len(row['idle']['processes'])}),flush=True)
    return row
try:
    build('prime');public=hashlib.sha256(reference.read_bytes()).hexdigest();original=hashlib.sha256(implementation.read_bytes()).hexdigest()
    for i in range(a.iterations):
        if memory()['availableMiB']<a.minimum_available_mb:
            report['stoppedForMemory']=True;break
        source.write_bytes(saved.replace(old,old+(' GC.KeepAlive("'+nonce+str(i)+'");').encode()))
        build('edit-'+str(i))
        assert hashlib.sha256(reference.read_bytes()).hexdigest()==public
        assert hashlib.sha256(implementation.read_bytes()).hexdigest()!=original
    source.write_bytes(saved)
    if not report.get('stoppedForMemory'):
        build('restore')
        assert hashlib.sha256(implementation.read_bytes()).hexdigest()==original
        report['outputRestored']=True
finally:
    source.write_bytes(saved);report['sourceRestored']=True;save()
