"""Profile native Linux cold worker actions, with uninstrumented controls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])
output=Path(sys.argv[1]).resolve(); output.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(ROOT/'tests/explicit_msbuild/perf.py'),str(output),'--sizes','128','--setup-only'],check=True)
folder=output/'128'; source=folder/'worker'; raw=folder/'raw'; results=[]
base=folder/'worker-base'
startup=[str(BAZEL),'--output_user_root='+str(folder/'user'),'--output_base='+str(base),'--ignore_all_rc_files']
flags=['--jobs=4','--disk_cache=','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4']
def run(name,command,cwd):
    start=time.perf_counter(); p=subprocess.run(list(map(str,command)),cwd=cwd,capture_output=True,text=True,timeout=600); seconds=time.perf_counter()-start
    (output/(name+'.log')).write_text(p.stdout+p.stderr)
    assert p.returncode==0,(name,(p.stdout+p.stderr)[-4000:])
    return seconds
for iteration,enabled in enumerate((False,True,False,True)):
    name=('profile' if enabled else 'control')+'-'+str(iteration)
    for build in source.rglob('BUILD.bazel'):
        text=build.read_text().replace('linux_worker=True, profile_build=True, ','linux_worker=True, ')
        if enabled:text=text.replace('linux_worker=True, ','linux_worker=True, profile_build=True, ')
        build.write_text(text)
    if iteration:
        run(name+'-clean',startup+['clean'],source)
        run(name+'-shutdown',startup+['shutdown'],source)
    setup=run(name+'-startup-analysis',startup+['build','//App','--nobuild']+flags,source)
    elapsed=run(name+'-build',startup+['build','//App','--profile='+str(output/(name+'.profile.gz'))]+flags,source)
    destination=output/name;destination.mkdir()
    worker_records=[]; compilation=[]
    for path in (base/'execroot/_main/bazel-out').glob('*/bin/*/*.diagnostics'):
        worker_file=path/'worker.json'
        if worker_file.exists():
            worker=json.loads(worker_file.read_text());worker['project']=path.parent.name;worker_records.append(worker)
        profile_file=path/'compile-profile.json'
        if profile_file.exists():compilation.append(json.loads(profile_file.read_text()))
    assert len(worker_records)==129,(name,len(worker_records))
    if enabled:assert len(compilation)==129,(name,len(compilation))
    (destination/'workers.json').write_text(json.dumps(worker_records,indent=2))
    (destination/'compilation.json').write_text(json.dumps(compilation,indent=2))
    row=dict(case=name,instrumented=enabled,startupAndAnalysisSeconds=setup,buildSeconds=elapsed,totalSeconds=setup+elapsed,workerCount=len({r['processId'] for r in worker_records}))
    results.append(row);(output/'results.json').write_text(json.dumps(results,indent=2)); print(row,flush=True)
run('worker-final-shutdown',startup+['shutdown'],source)
for i in range(2):
    run('raw-shutdown-'+str(i),[SDK/'dotnet','build-server','shutdown'],raw)
    for path in list(raw.rglob('bin'))+list(raw.rglob('obj')):shutil.rmtree(path)
    elapsed=run('raw-profile-'+str(i),[SDK/'dotnet','build','App/App.csproj','-c','Release','-m:4','-p:NuGetAudit=false','--nologo','-clp:PerformanceSummary'],raw)
    results.append(dict(case='raw-profile-'+str(i),buildSeconds=elapsed));print(results[-1],flush=True)
(output/'results.json').write_text(json.dumps(results,indent=2))
# Keep only benchmark artifacts in the bind mount. All builds stay on native disk.
if len(sys.argv)>2:
    evidence=Path(sys.argv[2]);evidence.mkdir(parents=True,exist_ok=True)
    for file in output.iterdir():
        if file.is_file():shutil.copyfile(file,evidence/file.name)
        elif file.name.startswith(('control-','profile-')):shutil.copytree(file,evidence/file.name,dirs_exist_ok=True)
