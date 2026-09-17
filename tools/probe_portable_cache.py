"""Portable-controller and native Bazel sandbox cache experiment (owned fixture)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from portable_cache import capture, environment, tool_identity, seed, publish, reset_workspace
from preparation_identity import digest
from protected_store import ProtectedStore
from prepare_graph import ROOT, DOTNET_ROOT
from probe_graph_execution import BAZEL
from probe_http_cache import CacheServer
from probe_bazel import json_stream
from starlark import call
from synthetic_graph import generate, name, source, oracle


def probe(output,count=10,repetitions=2,extended=True,delay_ms=0,retained=False,sandbox_probe_root=None,reuse_transfers=True,autoload_languages=False,overlap_startup=True,jvm_startup=False,preserve_module_lock=True):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    sdk=DOTNET_ROOT;dotnet=sdk/'dotnet'
    imports=[Path('/nix/store/dfhdbgnvv0jm1ld0hrzfaklgigvl7bzp-extra.targets'),Path('/nix/store/hm53cqanyh9f8dl3bij21iyhvk1mlb30-sign-apphost.proj')]
    report=dict(accepted=False,count=count,delayMs=delay_ms,scope='owned package-free net10 Release, macOS ARM64/Nix; explicit HTTP snapshot seeds; no cross-host or package qualification',samples=[],setup=[],retainedBazel=retained,reuseTransfers=reuse_transfers,autoloadLanguages=autoload_languages,overlapStartup=overlap_startup,jvmStartup=jvm_startup,preserveModuleLock=preserve_module_lock)
    def save():(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(label,args,cwd,env=None,check=True):
        t=time.perf_counter();r=subprocess.run(list(map(str,args)),cwd=cwd,env=env,capture_output=True,text=True,timeout=900)
        (output/(label+'.log')).write_text(r.stdout+r.stderr)
        if check and r.returncode:raise RuntimeError(label+' failed; see log')
        return time.perf_counter()-t,r.stdout+r.stderr,r.returncode
    run('bootstrap',[dotnet,'build',ROOT/'tools/NativeProjectCache','-c','Release','--nologo'],ROOT)
    controllers=[]
    for label in ('producer','consumer'):
        root=output/label;root.mkdir();tool=root/'tools';tool.mkdir()
        for suffix in ('.dll','.deps.json','.runtimeconfig.json'):shutil.copyfile(ROOT/f'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache{suffix}',tool/f'NativeProjectCache{suffix}')
        for filename in ('portable_cache.py','probe_native_cache.py','discovery_contract.py','preparation_identity.py','probe_portable_cache.py'):shutil.copyfile(ROOT/'tools'/filename,tool/filename)
        src=root/'src';spec=generate(src,count,'fan');home=root/'home';home.mkdir();temp=root/'tmp';temp.mkdir()
        env=environment(sdk,home,temp,src)
        elapsed,_,_=run(label+'-restore',[dotnet,'msbuild',spec['entry'],'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo'],src,env)
        report['setup'].append(dict(label=label,restoreSeconds=elapsed));controllers.append((root,tool,src,home))
    ordinary=output/'ordinary';generate(ordinary,count,'fan');raw_home=output/'raw-home';raw_home.mkdir();raw_temp=output/'raw-tmp';raw_temp.mkdir()
    raw_env=environment(sdk,raw_home,raw_temp,ordinary)
    run('raw-restore',[dotnet,'msbuild',spec['entry'],'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo'],ordinary,raw_env)
    store=ProtectedStore();sdk_identity=None;started=set()
    catalog=[];seed_snapshot=[];sdk_revision='original'
    with CacheServer(delay_ms) as server, ThreadPoolExecutor(max_workers=1) as startup_pool:
        def build(label,client,expected,compiled,*,bazel=True,read_probe=None,network_probe=None,write_probe=None,expected_failure=False,snapshot=None):
            nonlocal catalog,sdk_identity
            root,tool,src,home=controllers[client]
            tick=time.perf_counter();http_start=len(server.events)
            g=root/('g' if retained and bazel else label+'-g')
            module='module(name="portable_native_probe")\nbazel_dep(name="platforms", version="0.0.11")\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n'+call('local_dotnet_sdk',name='dotnet',path=str(sdk),external_imports=list(map(str,imports))) if bazel else None
            reset_workspace(g,module,preserve_lock=preserve_module_lock)
            starting=None;startup_seconds=0;sdk_seconds=0
            if bazel:
                for filename in ('msbuild.bzl','native_cache.bzl'):shutil.copyfile(ROOT/'bazel'/filename,g/filename)
                base=root/'b' if retained else output/(label+'-b')
                startup=[BAZEL,'--max_idle_secs=10','--nohome_rc','--noworkspace_rc','--output_base='+str(base),'--output_user_root='+str(output/'u')]
                if overlap_startup and base not in started:
                    # Load the required platform while SDK identity and seeds are prepared.
                    # Query loads metadata only; it cannot execute the MSBuild action.
                    warmup=['info','release'] if jvm_startup else ['query','@platforms//host:host','--output=label',*([] if autoload_languages else ['--incompatible_autoload_externally=']),'--profile='+str(output/(label+'-startup-profile.json.gz'))]
                    starting=startup_pool.submit(run,label+'-startup',[*startup,*warmup],g)
                    started.add(base)
            if sdk_identity is None:
                sdk_tick=time.perf_counter();sdk_identity=digest(store.snapshot(sdk.parents[1],[Path('/nix/store')]))
                sdk_seconds=time.perf_counter()-sdk_tick
                report['setup'].append(dict(sdkCaptureSeconds=sdk_seconds,chargedToCold=True,overlapped=overlap_startup))
            authored,restore,nodes=capture(src,home,sdk)
            runner_files=sorted(tool.glob('NativeProjectCache.*'));controller_files=sorted(tool.glob('*.py'))
            identity=tool_identity(sdk_identity,runner_files,controller_files,imports)
            manifest=dict(toolchain=digest(dict(identity=identity,sdkRevision=sdk_revision)),projects=nodes)
            for relative,data in authored.items():
                p=g/'src'/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            (g/'restore.json').write_text(json.dumps(restore,sort_keys=True));(g/'manifest.json').write_text(json.dumps(manifest,sort_keys=True))
            seeded=seed(server.url+'/native',catalog if snapshot is None else snapshot,manifest,g/'seeds')
            for p in runner_files:
                dest=g/'runner'/p.name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(p,dest)
            if bazel:
                (g/'BUILD.bazel').write_text('load(":native_cache.bzl", "msbuild_native_cache")\n'+call('msbuild_native_cache',name='n',project=spec['entry'],srcs=sorted('src/'+p for p in authored),seeds=sorted(p.relative_to(g).as_posix() for p in (g/'seeds').rglob('*') if p.is_file()),manifest='manifest.json',restore='restore.json',runner='runner/NativeProjectCache.dll',runner_support=['runner/NativeProjectCache.deps.json','runner/NativeProjectCache.runtimeconfig.json'],sdk='@dotnet//:files',dotnet='@dotnet//:sdk/dotnet',read_probe=read_probe or '',network_probe=network_probe or '',write_probe=write_probe or '',execution_nonce=label if label in ('corrupt','missing','sdk','empty','failed','readprobe','denywrite','denynet','outage','restored') else ''))
                if starting is not None:startup_seconds,_,_=starting.result()
                execution=output/(label+'-execution.json');prep=time.perf_counter()-tick
                action_http_start=len(server.events)
                # This generated workspace uses only our rule and native filegroups.
                autoload_flags=[] if autoload_languages else ['--incompatible_autoload_externally=']
                elapsed,log,code=run(label,[*startup,'build',*autoload_flags,'//:n','--jobs=2','--spawn_strategy=darwin-sandbox','--strategy=MsbuildNativeCache=darwin-sandbox','--remote_cache='+server.url+'/bazel','--noremote_cache_async','--remote_download_outputs=toplevel','--execution_log_json_file='+str(execution),'--profile='+str(output/(label+'-profile.json.gz')),'--noshow_progress','--color=no','--curses=no'],g,check=False)
                if network_probe is None:assert not any(e['path'].startswith('/native/') for e in server.events[action_http_start:]),'action contacted project cache'
                bundle=g/'bazel-bin/n.bundle';diagnostics=g/'bazel-bin/n.diagnostics'
                actions=[a for a in json_stream(execution) if a.get('mnemonic')=='MsbuildNativeCache'] if execution.exists() else []
                assert all(a.get('runner')=='remote cache hit' if a.get('cacheHit') else a.get('runner')=='darwin-sandbox' for a in actions)
            else:
                prep=time.perf_counter()-tick;bundle=root/(label+'-bundle');diagnostics=root/(label+'-diagnostics')
                request=dict(entry=spec['entry'],output=str(bundle),diagnostics=str(diagnostics),manifest=str(g/'manifest.json'),restore=str(g/'restore.json'),sources=[dict(source=str(g/'src'/p),destination=p) for p in authored],seeds=[dict(source=str(p),destination=p.relative_to(g/'seeds').as_posix()) for p in (g/'seeds').rglob('*') if p.is_file()])
                path=g/'request.json';path.write_text(json.dumps(request))
                elapsed,log,code=run(label,[dotnet,tool/'NativeProjectCache.dll','--portable-request',path],root,environment(sdk,home,root/'tmp',src),False);actions=[]
            if expected_failure:
                assert code!=0,'expected sandbox/build rejection'
                if label in ('denywrite','denyexternal'):assert 'permitted' in log.lower() or 'denied' in log.lower(),'missing OS denial evidence'
                if label=='failed':assert 'error CS' in log,'missing compiler failure evidence'
                assert not any(e['method']=='PUT' and e['path'].startswith('/native/') for e in server.events[http_start:]),'failure published project cache'
                if bazel:run(label+'-shutdown',[*startup,'shutdown'],g,check=False)
                report['samples'].append(dict(label=label,expectedFailure=True));save();return
            if code:raise RuntimeError(label+' failed; see log')
            outer_hit=bool(bazel and ((actions and actions[0].get('cacheHit')) or (retained and not actions)))
            actual=0 if outer_hit else json.loads((diagnostics/'action.json').read_text())['compiles']
            events=[] if outer_hit else json.loads((diagnostics/'events.json').read_text())
            assert actual==compiled,(label,actual,compiled)
            publication=publish(server.url+'/native',bundle/'cache',verified_blobs=seeded['verifiedBlobs'] if reuse_transfers else ());catalog=publication['entries']
            total=time.perf_counter()-tick
            _,app,_=run(label+'-app',[dotnet,bundle/'app'/f'{name(count-1)}.dll'],output,raw_env)
            assert app.strip()==expected,(label,app,expected)
            native_requests=[e for e in server.events[http_start:] if e['path'].startswith('/native/')]
            sample=dict(label=label,bazel=bazel,nativeGets=sum(e['method']=='GET' for e in native_requests),nativePuts=sum(e['method']=='PUT' for e in native_requests),seconds=total,startupSeconds=startup_seconds,sdkCaptureSeconds=sdk_seconds,preparationSeconds=prep,buildSeconds=elapsed,compiles=actual,publicationErrors=publication['errors'],hits=sum(e['kind']=='hit' for e in events),outerHit=outer_hit,seeds=len(seeded['accepted']),seedRejections=seeded['rejected'],http=server.totals(http_start),runtimeDllHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (bundle/'app').glob('*.dll')},toolchain=manifest['toolchain'],projects=nodes,actions=[dict(hit=a.get('cacheHit',False),runner=a.get('runner')) for a in actions])
            (output/(label+'-catalog.json')).write_text(json.dumps(catalog,indent=2));report['samples'].append(sample);save();print(label,round(total,3),actual,sample['hits'],outer_hit,flush=True)
            if bazel and not retained:run(label+'-shutdown',[*startup,'shutdown'],g)
            return sample
        def raw(label,expected,compiles):
            elapsed,log,_=run(label,[dotnet,'msbuild',spec['entry'],'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-graphBuild','-isolateProjects','-m:2','-nodeReuse:false','-nologo','-verbosity:normal','-p:PathMap='+str(ordinary)+'=/_/workspace'],ordinary,raw_env)
            actual=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines());assert actual==compiles,(label,actual)
            folder=ordinary/name(count-1)/'bin/Release/net10.0';_,app,_=run(label+'-app',[dotnet,folder/f'{name(count-1)}.dll'],output,raw_env);assert app.strip()==expected
            r=dict(label=label,seconds=elapsed,compiles=actual,runtimeDllHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.dll')});report['samples'].append(r);save();return r
        try:
            expected=oracle(spec['edges']);baseline=raw('cold-raw',expected,count)
            a=build('cold',0,expected,count);assert a['runtimeDllHashes']==baseline['runtimeDllHashes']
            seed_snapshot=catalog.copy()
            b=build('portable',1,expected,0,bazel=False);assert b['hits']==count and a['toolchain']==b['toolchain'] and a['projects']==b['projects'] and a['runtimeDllHashes']==b['runtimeDllHashes']
            for i in range(repetitions):
                b=build('recover'+str(i),1,expected,0,snapshot=seed_snapshot)
                assert b['runtimeDllHashes']==a['runtimeDllHashes']
                if i>0:assert b['outerHit'],'unchanged seed snapshot should hit outer Bazel cache'
            for i in range(repetitions):
                for src in (controllers[1][2],ordinary):(src/'N0000/Value.cs').write_text(source(0,[],False).replace('1L',str(1+7*(i+1))+'L'))
                expected=str(int(oracle(spec['edges']))+(int(oracle(spec['edges'],0))-int(oracle(spec['edges'])))*(i+1))
                baseline=raw('body'+str(i)+'-raw',expected,1)
                b=build('body'+str(i),1,expected,1);assert b['hits']==count-1 and b['runtimeDllHashes']==baseline['runtimeDllHashes']
            if extended:
                for src in (controllers[1][2],ordinary):
                    p=src/'N0000/Value.cs';p.write_text(p.read_text().replace('public static long Read()','public static int AddedApi() => 42; public static long Read()'))
                raw('api-raw',expected,3);build('api',1,expected,3)
                # Bad remote payload is rejected by broker and the sandbox recompiles it.
                victim=next(r for r in catalog if r['project']=='N0000/N0000.csproj');server.data['/native/cas/'+victim['blob']]=b'corrupt'
                b=build('corrupt',1,expected,1);assert len(b['seedRejections'])==1
                victim=next(r for r in catalog if r['project']=='N0000/N0000.csproj');server.data.pop('/native/cas/'+victim['blob'])
                b=build('missing',1,expected,1);assert len(b['seedRejections'])==1
                sdk_revision='different-identity';build('sdk',1,expected,count);sdk_revision='original'
                build('empty',1,expected,count,snapshot=[])
                saved_catalog=catalog.copy();server.offline_prefixes=['/native/']
                b=build('outage',1,expected,count);assert b['publicationErrors']
                server.offline_prefixes=[]
                b=build('restored',1,expected,0,snapshot=saved_catalog);assert b['hits']==count
                if sandbox_probe_root is None:raise ValueError('extended probe requires --sandbox-probe-root outside temporary directories')
                sandbox_probe_root=Path(sandbox_probe_root).resolve();sandbox_probe_root.mkdir(parents=True,exist_ok=True)
                outside=sandbox_probe_root/(output.name+'-sentinel')
                with outside.open('x') as f:f.write('owned outside-write sentinel')
                build('readprobe',1,expected,0,read_probe=str(outside))
                report['absoluteReadAllowed']=True
                build('denywrite',1,expected,0,write_probe=str(outside),expected_failure=True)
                assert outside.read_text()=='owned outside-write sentinel'
                report['outsideWriteDenied']=True
                probe_path='/native/cas/'+hashlib.sha256(b'network sentinel').hexdigest();server.data[probe_path]=b'network sentinel'
                build('loopback',1,expected,0,network_probe=server.url+probe_path)
                assert any(e['path']==probe_path for e in server.events),'missing loopback probe evidence'
                report['loopbackAllowed']=True
                build('denyexternal',1,expected,0,network_probe='http://192.0.2.1:9',expected_failure=True)
                report['externalNetworkDenied']=True
                p=controllers[1][2]/'N0000/Value.cs';p.write_text('not valid C#')
                build('failed',1,expected,0,expected_failure=True)
            report['accepted']=True
        except BaseException as error:report['failure']=str(error);raise
        finally:
            if retained:
                for root,_,_,_ in controllers:
                    if (root/'g/BUILD.bazel').exists():run(root.name+'-shutdown',[BAZEL,'--nohome_rc','--noworkspace_rc','--output_base='+str(root/'b'),'--output_user_root='+str(output/'u'),'shutdown'],root/'g',check=False)
            report['http']=server.totals();(output/'http-events.json').write_text(json.dumps(server.events,indent=2));save()
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--nodes',type=int,default=10);p.add_argument('--repetitions',type=int,default=2);p.add_argument('--no-extended',action='store_true');p.add_argument('--delay-ms',type=float,default=0);p.add_argument('--retained',action='store_true');p.add_argument('--sandbox-probe-root',type=Path);p.add_argument('--discard-module-lock',action='store_true',help='Control: discard the generated Bazel module lock');p.add_argument('--jvm-startup',action='store_true',help='Control: overlap only JVM launch, without platform metadata');p.add_argument('--serial-startup',action='store_true',help='Control: start Bazel only after SDK and seed preparation');p.add_argument('--autoload-languages',action='store_true',help='Control: retain Bazel automatic external language-rule loading');p.add_argument('--repeat-uploads',action='store_true',help='Control: upload even byte-identical verified seeds')
    a=p.parse_args();probe(a.output,a.nodes,a.repetitions,not a.no_extended,a.delay_ms,a.retained,a.sandbox_probe_root,not a.repeat_uploads,a.autoload_languages,not a.serial_startup,a.jvm_startup,not a.discard_module_lock)
