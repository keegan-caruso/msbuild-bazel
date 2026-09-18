"""Compare whole-graph and per-project Bazel caching on larger synthetic graphs."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from cache_service import CacheService
from workload import ROOT,SDK,BAZEL,environment,generate,oracle,diamond_source,hashes,remove,shutdown


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,shape=a.shape,notes=('Bazel locked restore included; ' if a.locked_restore else 'Restore excluded; ')+ ' raw builds supply output oracles, not incremental timing baselines. Warm edits reuse the fresh-hit worker; fresh edits use separate workers. Loopback cache, jobs=2.',cases=[],raw=[])
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def fixture(base,count,restore=True):
        base.mkdir(parents=True);source=base/'source';graph=generate(source,count,a.shape)
        props=source/'Directory.Build.props';props.write_text(props.read_text().replace('TargetFramework>','TargetFrameworks>'))
        if not restore:return source,graph
        p=subprocess.run([str(SDK/'dotnet'),'msbuild',graph['entry'],'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-p:RestoreConfigFile='+str(source/'NuGet.Config'),'-nodeReuse:false','-nologo']+(['-p:RestorePackagesWithLockFile=true'] if a.locked_restore else []),cwd=source,env=environment(source,a.packages),capture_output=True,text=True,timeout=600)
        (base/'restore.log').write_text(p.stdout+p.stderr);assert p.returncode==0
        return source,graph
    def edit(source,graph,index):
        (source/f'N{index:04d}/Value.cs').write_text(diamond_source(index,graph['edges'][index],False,True))
    try:
        for count in a.nodes:
            rawbase=out/str(count)/'raw';source,graph=fixture(rawbase,count)
            expected={};entry=graph['entry'];assembly=Path(entry).stem;runtime=Path(entry).parent/'bin/Release/net10.0'
            for label,index in [('unchanged',None),('shared',0),('leaf',count//2)]:
                for n in range(count):(source/f'N{n:04d}/Value.cs').write_text(diamond_source(n,graph['edges'][n],n==count-1,n==index))
                begin=time.perf_counter()
                p=subprocess.run([str(SDK/'dotnet'),'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-p:PathMap='+str(source)+'=/_/workspace','-nodeReuse:false','-nologo','-v:normal'],cwd=source,env=environment(source,a.packages),capture_output=True,text=True,timeout=900)
                (rawbase/(label+'.log')).write_text(p.stdout+p.stderr);assert p.returncode==0
                observed=subprocess.check_output([str(SDK/'dotnet'),str(source/runtime/(assembly+'.dll'))],text=True).strip();assert observed==oracle(graph['edges'],index)
                expected[label]=hashes(source/runtime)
                report['raw'].append(dict(nodes=count,case=label,seconds=time.perf_counter()-begin,managedHashes=expected[label]));save()
            locks={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('packages.lock.json')} if a.locked_restore else {}
            for mode in a.modes:
                root=out/str(count)/mode;layout=None
                if a.locked_restore:
                    assert mode=='projects' and a.direct_checkout and a.layout_root and locks
                    root.mkdir(parents=True,exist_ok=True)
                    layout=root/'project-layout.json';layout.write_bytes((a.layout_root/str(count)/mode/'project-layout.json').read_bytes())
                with CacheService(a.cache_binary,root/'server') as server:
                    def invoke(label,snapshot=None,index=None,reuse=None,keep=False):
                        base=root/(reuse or label)
                        if reuse:local=base/'source'
                        else:
                            local,_=fixture(base,count,restore=not a.locked_restore)
                            if a.locked_restore:
                                for name,data in locks.items():(local/name).write_bytes(data)
                                assert not list(local.rglob('project.assets.json'))
                        if index is not None:edit(local,graph,index)
                        request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(local),state=str(base/'state'),output=str(base/'result'),entry=entry,operation='build',**{'nuget-packages':str(a.packages),'bazel-remote-cache':server.url,'bazel-remote-upload':label=='producer','bazel-install-cache':str(a.bazel_install_cache),'bazel-repository-cache':str(a.bazel_repository_cache)})
                        if mode=='projects':
                            request['project-actions']=True
                            if layout:request['project-layout']=str(layout)
                        else:
                            request['remote-endpoint']=server.url+'/native'
                            if snapshot:request['remote-snapshot']=snapshot
                        if a.direct_checkout:request['direct-checkout']=True
                        if a.locked_restore:request['locked-restore']=True
                        path=base/'request.json';path.write_text(json.dumps(request));begin=time.perf_counter()
                        try:
                            p=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(path)],cwd=ROOT,capture_output=True,text=True,timeout=1800)
                            (base/'command.log').write_text(p.stdout+p.stderr)
                            value=json.loads((base/'result/report.json').read_text());value['wallSeconds']=time.perf_counter()-begin
                            metrics = {}
                            for log in ['execution.json','discovery-execution.json']:
                                path = base/'result'/log
                                if not path.exists():continue
                                content=path.read_text();decoder=json.JSONDecoder();offset=0
                                while offset<len(content):
                                    while offset<len(content) and content[offset].isspace():offset+=1
                                    if offset==len(content):break
                                    event,offset=decoder.raw_decode(content,offset)
                                    if event.get('cacheHit'):continue
                                    seconds=float(event.get('metrics',{}).get('executionWallTime','0s')[:-1])
                                    metrics.setdefault(event.get('mnemonic','unknown'),[]).append(seconds)
                            value['actionExecutionSeconds']={name:dict(count=len(times),total=sum(times),maximum=max(times)) for name,times in metrics.items()}
                            report['cases'].append(dict(nodes=count,mode=mode,case=label,result=value));save()
                            assert p.returncode==0 and value['accepted'],str(base/'command.log')
                            if a.direct_checkout:assert not (base/'state/g/inputs').exists() and not value['nuget']['staged']
                            app=base/'state/g/bazel-bin/build.bundle/app'
                            assert subprocess.check_output([str(SDK/'dotnet'),str(app/(assembly+'.dll'))],text=True).strip()==oracle(graph['edges'],index)
                            assert hashes(app)==expected['unchanged' if index is None else 'shared' if index==0 else 'leaf']
                            assert value['compiles']==(count if label=='producer' else 1 if index is not None else 0)
                            if mode=='projects' and label=='fresh-hit':assert value['MsbuildCompileProject']['remoteHits']==count
                            if mode=='projects' and index is not None and not reuse:assert value['MsbuildCompileProject']['remoteHits']==count-1
                            if layout:assert value['bazelInvocations']==1
                            if a.locked_restore:
                                assert not list(local.rglob('project.assets.json'))
                                assert value['MsbuildLockedRestore']['executed']==(1 if label=='producer' else 0)
                                if label in ('fresh-hit','shared-edit','leaf-edit'):assert value['MsbuildLockedRestore']['remoteHits']==1
                            value['rawParity']=True;save()
                            print(count,mode,label,round(value['wallSeconds'],3),value['compiles'],value.get('MsbuildCompileProject'),flush=True)
                            return value
                        finally:
                            if not keep:shutdown(base)
                    producer=invoke('producer');snapshot=producer.get('publishedSnapshot')
                    if mode=='projects' and a.declared_layout:
                        layout=root/'project-layout.json';layout.write_bytes((root/'producer/result/project-layout.json').read_bytes())
                    remove(root/'producer')
                    invoke('fresh-hit',snapshot,keep=True)
                    try:
                        for repetition in range(3):
                            (root/'fresh-hit/result').rename(root/'fresh-hit'/('result-'+str(repetition)))
                            invoke('warm-'+str(repetition),snapshot,reuse='fresh-hit',keep=True)
                        for label,index in [('warm-shared-edit',0),('warm-restored',None),('warm-leaf-edit',count//2)]:
                            if index is None:(root/'fresh-hit/source/N0000/Value.cs').write_text(diamond_source(0,graph['edges'][0],False,False))
                            (root/'fresh-hit/result').rename(root/'fresh-hit'/('before-'+label))
                            invoke(label,snapshot,index=index,reuse='fresh-hit',keep=True)
                    finally:shutdown(root/'fresh-hit')
                    invoke('shared-edit',snapshot,index=0)
                    invoke('leaf-edit',snapshot,index=count//2)
                    server.capture('final')
        report['accepted']=True
    finally:save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['output','cache-binary','packages','bazel-install-cache','bazel-repository-cache']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--nodes',nargs='+',type=int,default=[16,64]);p.add_argument('--shape',choices=['fan','chain'],default='fan')
    p.add_argument('--locked-restore',action='store_true')
    p.add_argument('--layout-root',type=Path)
    p.add_argument('--direct-checkout',action='store_true')
    p.add_argument('--declared-layout',action='store_true')
    p.add_argument('--modes',nargs='+',choices=['whole','projects'],default=['whole','projects'])
    run(p.parse_args())
