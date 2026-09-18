"""Shared fixtures/oracles for real-service worker acceptance and measurements."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from synthetic_graph import generate, oracle, source as diamond_source
from probe_serilog_tests import REVISION, PROJECT, ASSEMBLY, APPROVED, FACT, parse_results
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])
TESTS=dict(data=['test/Serilog.ApprovalTests/ApiApprovalTests.cs',APPROVED],expectedTests=[FACT])


def remove(path):
    if path.exists():
        for directory,_,_ in os.walk(path,followlinks=False):os.chmod(directory,0o700)
        shutil.rmtree(path)


def environment(source,packages):
    return dict(os.environ,DOTNET_ROOT=str(SDK),NUGET_PACKAGES=str(packages),
        DOTNET_CLI_HOME=str(source.parent/'home'),MSBUILDDISABLENODEREUSE='1',
        MSBuildEnableWorkloadResolver='false',CI='true',DiffEngine_Disabled='true',
        SHOULDLY_SOURCE_PATH_MAP=str(source)+'=/_/workspace')


def fixture(base,kind,packages,checkout=None):
    base.mkdir(parents=True,exist_ok=False);source=base/'source'
    if kind=='diamond':
        graph=generate(source,4,'fan');props=source/'Directory.Build.props'
        props.write_text(props.read_text().replace('TargetFramework>','TargetFrameworks>'))
        entry=graph['entry']
    else:
        archive=subprocess.check_output(['git','-C',str(checkout),'archive',REVISION])
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:contents.extractall(source,filter='data')
        entry=PROJECT
    config=next(p for p in source.iterdir() if p.name.lower()=='nuget.config')
    result=subprocess.run([str(SDK/'dotnet'),'msbuild',entry,'-t:Restore','-p:RestoreConfigFile='+str(config),'-p:Configuration=Release',
        '-p:TargetFramework=net10.0','-nodeReuse:false','-nologo'],cwd=source,env=environment(source,packages),capture_output=True,text=True,timeout=300)
    (base/'restore.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('restore failed: '+str(base/'restore.log'))
    return source


def mutate(source,kind,case):
    if case not in ('body','api','failed-test'):return
    if kind=='diamond':
        path=source/'N0000/Value.cs'
        if case=='body':path.write_text(diamond_source(0,[],False,True))
        else:path.write_text(path.read_text().replace('public static class Value {','public static class Value { public static int WorkerApi() => 7;'))
    else:
        path=source/'src/Serilog/Log.cs';text=path.read_text()
        if case=='body':text=text.replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);','public static bool IsEnabled(LogEventLevel level) => false;')
        elif case=='api':
            text=text.replace('public static bool IsEnabled(LogEventLevel level)', 'public static bool IsEnabled(LogEventLevel level, bool workerProbe = false)')
            # Keep the XML documentation warning policy intact.
            text=text.replace('    public static bool IsEnabled(LogEventLevel level, bool workerProbe = false)', '    /// <param name="workerProbe">Worker cache probe.</param>\n    public static bool IsEnabled(LogEventLevel level, bool workerProbe = false)')
            approved=source/APPROVED
            approved.write_text(approved.read_text().replace('public static bool IsEnabled(Serilog.Events.LogEventLevel level)', 'public static bool IsEnabled(Serilog.Events.LogEventLevel level, bool workerProbe = false)'))
        elif case=='failed-test':
            approved=source/APPROVED;approved.write_text(approved.read_text()+'\nintentional mismatch\n')
        path.write_text(text)


OFFLINE_PROFILE='(version 1)(allow default)(deny network-outbound)(allow network-outbound (remote ip "localhost:*") (remote unix-socket))'


def hashes(folder):
    return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file() and p.suffix in ('.dll','.pdb')}


def shutdown(base):
    state=base/'state'
    if (state/'g').exists():
        command=[str(BAZEL),'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base='+str(state/'b'),
            '--output_user_root='+str(state/'u')]
        report=base/'result/report.json'
        if report.exists():
            install=json.loads(report.read_text()).get('bazelInstallBase')
            if install:command.append('--install_base='+install)
        subprocess.run(command+['shutdown'],cwd=state/'g',capture_output=True,check=True)


def native(base,source,kind,packages,endpoint,snapshot=None,failed=False,install_cache=None,repository_cache=None,disable_repository_downloads=False,action_cache=None,action_upload=False,lease_mutation=False):
    entry='N0003/N0003.csproj' if kind=='diamond' else PROJECT
    request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(source),state=str(base/'state'),
        entry=entry,output=str(base/'result'),operation='build' if kind=='diamond' else 'test',reuse=True,
        **{'independent-workers':True,'nuget-packages':str(packages),'remote-endpoint':endpoint,'force-tests':True})
    if action_cache:request['bazel-remote-cache']=action_cache
    if action_upload:request['bazel-remote-upload']=True
    if disable_repository_downloads:request['bazel-disable-repository-downloads']=True
    if repository_cache:request['bazel-repository-cache']=str(repository_cache.resolve())
    if install_cache:request['bazel-install-cache']=str(install_cache.resolve())
    if kind=='serilog':request['tests']=TESTS
    if snapshot:request['remote-snapshot']=snapshot
    path=base/'request.json';path.write_text(json.dumps(request))
    begin=time.perf_counter()
    command=[str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'workflow','--request',str(path)]
    stopped=threading.Event();applied=threading.Event()
    def mutation():
        while not stopped.wait(.01):
            if (base/'state/g/BUILD.bazel').exists():
                path=base/'state/workspace/src/Serilog/Log.cs'
                path.write_bytes(path.read_bytes()+b'\n// live lease mutation\n');applied.set();return
    worker=threading.Thread(target=mutation,daemon=True) if lease_mutation else None
    if worker:worker.start()
    try:process=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=900)
    finally:
        stopped.set()
        if worker:worker.join()
    if lease_mutation:assert applied.is_set(), 'lease mutation was not exercised'
    seconds=time.perf_counter()-begin;(base/'command.log').write_text(process.stdout+process.stderr)
    value=json.loads((base/'result/report.json').read_text());value['wallSeconds']=seconds
    if (process.returncode!=0)!=failed or value['accepted']==failed:raise RuntimeError('native result differs: '+str(base/'command.log'))
    if not failed:
        if not value['workerCacheEligible']:raise AssertionError(value)
        if 'publishedSnapshot' not in value['remote']:raise AssertionError(value)
        app=base/'state/g/bazel-bin/build.bundle/app'
        value['managedHashes']=hashes(app)
        if kind=='diamond':
            run_begin=time.perf_counter()
            actual=subprocess.check_output([str(SDK/'dotnet'),str(app/'N0003.dll')],text=True).strip()
            value['wallSeconds']+=time.perf_counter()-run_begin
            graph=json.loads((source/'synthetic.json').read_text())
            changed=0 if '8L' in (source/'N0000/Value.cs').read_text() else None
            assert actual==oracle(graph['edges'],changed),actual
            value['applicationOutput']=actual
        else:
            assert value['test']['passed'] and value['test']['runtimeHashes']==value['runtimeHashes'],value
    return value


def raw(base,source,kind,packages,label='result',test=True):
    destination=base/label;destination.mkdir()
    entry='N0003/N0003.csproj' if kind=='diamond' else PROJECT
    begin=time.perf_counter()
    path_map=str(source)+'=/_/workspace'
    if kind=='serilog':path_map+='%2C'+str(packages)+'=/_/workspace/.nuget/packages'
    command=[str(SDK/'dotnet'),'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0',
        '-p:PathMap='+path_map,'-nodeReuse:false','-nologo','-v:normal']
    result=subprocess.run(command,cwd=source,env=environment(source,packages),capture_output=True,text=True,timeout=600)
    log=result.stdout+result.stderr;(destination/'build.log').write_text(log)
    if result.returncode:raise RuntimeError('raw build failed: '+str(destination))
    build=time.perf_counter()-begin
    compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
    app=source/('N0003/bin/Release/net10.0' if kind=='diamond' else str(Path(ASSEMBLY).parent))
    if test:
        args=[str(SDK/'dotnet'),str(app/'N0003.dll')] if kind=='diamond' else [str(SDK/'dotnet'),'vstest',str(app/'Serilog.ApprovalTests.dll'),'--logger:trx;LogFileName=results.trx','--ResultsDirectory:'+str(destination)]
        result=subprocess.run(args,cwd=source,env=environment(source,packages),capture_output=True,text=True,timeout=300)
        (destination/'test.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError('raw test failed: '+str(destination))
    seconds=time.perf_counter()-begin
    value=dict(seconds=seconds,compiles=compiles,phases=dict(build=build,run=seconds-build),managedHashes=hashes(app))
    if test and kind=='serilog':
        value['test']=parse_results(destination/'results.trx');assert value['test']['passed']==1
    if test and kind=='diamond':value['applicationOutput']=result.stdout.strip()
    return value
