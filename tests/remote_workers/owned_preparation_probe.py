"""Qualify Bazel-owned preparation, build/test recovery, and input invalidation."""
import argparse
import json
import subprocess
import time
import threading
from pathlib import Path
from cache_service import CacheService
from workload import ROOT,SDK,BAZEL,TESTS,fixture,mutate,raw,hashes,remove,shutdown


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),cases=[],oracles=[])
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for kind in a.workloads:
            root=out/kind;root.mkdir()
            with CacheService(a.cache_binary,root/'server') as server:
                def invoke(label,key=None,edit=None,upload=True,probe=None,expect_failure=False,live=False,extra_source=False,reuse=None,keep_server=False):
                    base=root/(reuse or label);source=base/'source' if reuse else fixture(base,kind,a.packages,a.checkout)
                    if edit:mutate(source,kind,edit)
                    if extra_source:(source/'N0000/Added.cs').write_text('public static class Added { public static int Value => 7; }\n')
                    request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(source),state=str(base/'state'),output=str(base/'result'),entry='N0003/N0003.csproj' if kind=='diamond' else 'test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj',operation='build' if kind=='diamond' else 'test',**{'nuget-packages':str(a.packages),'bazel-remote-cache':server.url,'bazel-remote-upload':upload,'remote-endpoint':server.url+'/native','bazel-install-cache':str(a.bazel_install_cache),'bazel-repository-cache':str(a.bazel_repository_cache)})
                    if kind=='serilog':request['tests']=TESTS
                    if key:request['remote-snapshot']=key
                    if probe:
                        project=source/request['entry']
                        project.write_text(project.read_text().replace('</Project>', '<PropertyGroup><UndeclaredProbe>$([System.IO.File]::ReadAllText(&quot;'+str(probe)+'&quot;))</UndeclaredProbe></PropertyGroup></Project>'))
                    path=base/'request.json';path.write_text(json.dumps(request));start=time.perf_counter()
                    stopped=threading.Event();applied=threading.Event()
                    def mutation():
                        while not stopped.wait(.01):
                            if (base/'state/g/BUILD.bazel').exists():
                                target=source/('N0000/Class1.cs' if kind=='diamond' else 'src/Serilog/Log.cs')
                                # Add a file to the original checkout after staging. The final
                                # namespace verification must reject publication even on a hit.
                                (target.parent/'LeaseMutation.cs').write_text('// live input mutation\n')
                                applied.set();return
                    worker=threading.Thread(target=mutation,daemon=True) if live else None
                    if worker:worker.start()
                    try:
                        p=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=900)
                        (base/'command.log').write_text(p.stdout+p.stderr)
                        value=json.loads((base/'result/report.json').read_text());value['wallSeconds']=time.perf_counter()-start
                        report['cases'].append(dict(kind=kind,case=label,result=value));save()
                        if value['accepted']==expect_failure or (p.returncode!=0)!=expect_failure:raise RuntimeError('Unexpected result: '+str(base/'command.log'))
                        if not expect_failure:
                            app=base/'state/g/bazel-bin/build.bundle/app';value['managedHashes']=hashes(app)
                            if kind=='diamond':value['applicationOutput']=subprocess.check_output([str(SDK/'dotnet'),str(app/'N0003.dll')],text=True).strip()
                            else:assert value['test']['passed']
                        print(kind,label,value['accepted'],value.get('MsbuildPrepare'),value.get('MsbuildNativeCache'),value.get('compiles'),round(value['wallSeconds'],3),flush=True)
                        save();return value
                    finally:
                        stopped.set()
                        if worker:worker.join();assert applied.is_set()
                        if not keep_server:shutdown(base)
                p=invoke('producer');key=p['publishedSnapshot'];assert p['compiles']==(4 if kind=='diamond' else 2)
                remove(root/'producer')
                assert p['cachePrime']['accepted'] and p['cachePrime']['compiles']==0
                hit=invoke('fresh-hit',key,upload=False,keep_server=True);assert hit['compiles']==0 and hit['MsbuildPrepare']['remoteHits']==1 and hit['MsbuildNativeCache']['remoteHits']==1
                assert hit['managedHashes']==p['managedHashes']
                try:
                    for repetition in range(3):
                        (root/'fresh-hit/result').rename(root/'fresh-hit'/('result-'+str(repetition)))
                        warm=invoke('warm-'+str(repetition),key,upload=False,reuse='fresh-hit',keep_server=True)
                        assert warm['MsbuildPrepare']['executed']==0 and warm['compiles']==0 and warm['managedHashes']==hit['managedHashes']
                finally:shutdown(root/'fresh-hit')
                changed=invoke('body-edit',key,'body',upload=False);assert changed['compiles']==1 and changed['MsbuildPrepare']['executed']==1
                rb=root/'raw';rs=fixture(rb,kind,a.packages,a.checkout);ordinary=raw(rb,rs,kind,a.packages);assert ordinary['managedHashes']==hit['managedHashes']
                mutate(rs,kind,'body');edited=raw(rb,rs,kind,a.packages,label='body');assert edited['managedHashes']==changed['managedHashes']
                report['oracles'].extend([dict(kind=kind,case='unchanged',result=ordinary),dict(kind=kind,case='body',result=edited)]);save()
                def puts():return sum(float(l.rsplit(' ',1)[1]) for l in server.read('/metrics').decode().splitlines() if l.startswith('http_request_duration_seconds_count{') and 'method="PUT"' in l)
                if kind=='diamond':
                    hidden=root/'hidden';hidden.write_text('undeclared');before=puts()
                    rejected=invoke('undeclared-read',key,probe=hidden,expect_failure=True)
                    assert puts()==before and rejected['actionCache']['publishedObjects']==0
                    assert 'Access to the path' in (root/'undeclared-read/result/bazel.log').read_text()
                    added=invoke('added-source',key,upload=False,extra_source=True)
                    assert added['MsbuildPrepare']['executed']==1 and added['compiles']>0
                    addedbase=root/'raw-added';addedsrc=fixture(addedbase,kind,a.packages,a.checkout)
                    (addedsrc/'N0000/Added.cs').write_text('public static class Added { public static int Value => 7; }\n')
                    addedraw=raw(addedbase,addedsrc,kind,a.packages)
                    assert addedraw['managedHashes']==added['managedHashes']
                    report['oracles'].append(dict(kind=kind,case='added-source',result=addedraw));save()
                else:
                    before=puts();rejected=invoke('failed-test',key,edit='failed-test',expect_failure=True)
                    assert rejected['actionCache']['stagedObjects']>0 and rejected['actionCache']['publishedObjects']==0 and puts()==before
                before=puts();rejected=invoke('live-mutation',key,edit='body',live=True,expect_failure=True)
                assert rejected['actionCache']['publishedObjects']==0 and puts()==before
                assert 'Leased inputs changed' in (root/'live-mutation/command.log').read_text()
                server.capture('final')
        report['accepted']=True
    finally:save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['output','cache-binary','packages','checkout','bazel-install-cache','bazel-repository-cache']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--workloads',nargs='+',default=['diamond','serilog'])
    run(p.parse_args())
