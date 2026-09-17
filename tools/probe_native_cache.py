"""Owned synthetic-only MSBuild project cache experiment with fresh workspaces."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from xml.etree import ElementTree as ET

from discovery_contract import check_xml, SDK_SWITCHES
from preparation_identity import tree_snapshot, digest
from protected_store import ProtectedStore
from prepare_graph import ROOT, DOTNET_ROOT
from probe_graph_cache import cache_environment
from synthetic_graph import generate, name, source, oracle


def input_hash(relative, data, workspace):
    # Only generated restore metadata contains relocatable workspace paths.
    # Authored bytes, including string literals, are part of the exact input.
    if "obj" in Path(relative).parts:
        data = data.replace(str(workspace).encode(), b"${WORKSPACE}")
    return hashlib.sha256(data).hexdigest()


def qualify(root):
    # Reuse namespace/content capture and authored XML grammar, then narrow it to
    # the owned fixture's package-free SDK-only execution surface.
    tree_snapshot(root,[root])
    sdk=json.loads((root/'global.json').read_text()).get('sdk',{})
    if sdk!={'version':'10.0.400','rollForward':'disable'}:raise ValueError('unqualified SDK selection')
    projects={};kinds={}
    for p in root.rglob('*.csproj'):
        rel=p.relative_to(root)
        if len(rel.parts)!=2 or p.stem!=p.parent.name:raise ValueError('unqualified project layout')
        check_xml(p); tree=ET.parse(p)
        allowed={'Project','PropertyGroup','ItemGroup','ProjectReference','OutputType'}
        if any(e.tag not in allowed for e in tree.iter()):raise ValueError('unqualified project XML')
        kinds[str(p.relative_to(root))]=tree.findtext('PropertyGroup/OutputType','Library')
        if kinds[str(p.relative_to(root))] not in ('Library','Exe'):raise ValueError('unqualified output type')
        if any('$' in (e.text or '') for e in tree.iter()):raise ValueError('project property expressions unsupported')
        deps=[]
        for e in tree.iter():
            if e.tag=='ProjectReference':
                if set(e.attrib)!={'Include'}:raise ValueError('unqualified reference metadata')
                deps.append(str((p.parent/e.attrib['Include']).resolve().relative_to(root)))
            elif e.tag!='Project' and e.attrib:raise ValueError('unqualified project attributes')
        projects[str(p.relative_to(root))]=sorted(deps)
    if len({Path(p).stem for p in projects})!=len(projects):raise ValueError('assembly name collision')
    if any(kinds.get(d)!='Library' for deps in projects.values() for d in deps):raise ValueError('unqualified dependency')
    props=root/'Directory.Build.props';check_xml(props)
    allowed={'Project','PropertyGroup','TargetFramework','UseAppHost','UseSharedCompilation','EnableNETAnalyzers','Deterministic','DisableTransitiveProjectReferences','Nullable','DefineConstants'}
    if any(e.tag not in allowed or e.attrib or ('$' in (e.text or '')) for e in ET.parse(props).iter()):raise ValueError('unqualified props')
    values={e.tag:(e.text or '').strip() for e in ET.parse(props).iter()}
    if values.get('TargetFramework')!='net10.0' or any(values.get(k)!=v for k,v in SDK_SWITCHES.items()):raise ValueError('required SDK switches missing or changed')
    for p in root.rglob('*'):
        if p.is_symlink():raise ValueError('fixture symlinks unsupported')
        if not p.is_file():continue
        rel=p.relative_to(root)
        if p.name in ('global.json','NuGet.Config','Directory.Build.props','synthetic.json') and len(rel.parts)!=1:raise ValueError('nested control file unsupported')
        if p.suffix=='.cs' and rel.parts[0] not in {str(Path(project).parent) for project in projects}:raise ValueError('source outside declared projects')
        if 'obj' in rel.parts:
            if len(rel.parts)!=3 or p.suffix not in ('.json','.props','.targets') and p.name!='project.nuget.cache':raise ValueError('unexpected restore input')
            if p.suffix in ('.props','.targets'):
                check_xml(p)
                if any(e.tag.rsplit('}',1)[-1]=='Import' for e in ET.parse(p).iter()):raise ValueError('restore imports unsupported')
            if p.name=='project.assets.json' and any(v['type']!='project' for v in json.loads(p.read_text())['libraries'].values()):raise ValueError('packages unsupported')
        elif p.name not in ('global.json','NuGet.Config','Directory.Build.props','synthetic.json') and p.suffix not in ('.cs','.csproj'):
            raise ValueError('undeclared fixture input: '+str(rel))
    return projects


def probe(output,count=10,repetitions=2,extended=True,remote_server=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    subject=output/'source';ordinary=output/'ordinary';spec=generate(subject,count,'fan');generate(ordinary,count,'fan')
    dotnet=DOTNET_ROOT/'dotnet';entry=spec['entry'];plugin=ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'
    cache=output/'cache';cache.mkdir();work=output/'w'
    targets=output/'Cache.targets';targets.write_text(f'<Project><ItemGroup Condition="\'$(NativeCacheEnabled)\' == \'true\'"><ProjectCachePlugin Include="{plugin}" /></ItemGroup></Project>')
    report=dict(accepted=False,scope='owned synthetic package-free fixture; no sandbox or remote qualification',count=count,samples=[],setup=[],cachePolicy='fresh workspace on every native build; direct dependency API hashes; runtime composition',performanceQualified=False)
    def save():(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(label,args,cwd,extra=None,check=True):
        t=time.perf_counter();r=subprocess.run(list(map(str,args)),cwd=cwd,env=dict(cache_environment(output,cwd),**(extra or {})),capture_output=True,text=True,timeout=600)
        elapsed=time.perf_counter()-t;log=r.stdout+r.stderr;(output/(label+'.log')).write_text(log)
        if check and r.returncode:raise RuntimeError(label+' failed; see log')
        return elapsed,log,r.returncode
    def assembly(root):return root/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
    def command(root,enabled):return [dotnet,'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-graphBuild','-isolateProjects','-m:2','-nodeReuse:false','-nologo','-verbosity:normal',f'-p:PathMap={root}=/_/workspace',f'-p:DirectoryBuildTargetsPath={targets}','-p:NativeCacheEnabled='+str(enabled).lower()]
    identity=None
    sdk_revision="original"
    def measure(mode,label,expected,compiles=None,working=None):
        nonlocal identity
        t=time.perf_counter();prep=0;events=[];root=ordinary
        if mode=='native':
            root=working or (output/"consumer" if remote_server and label!="cold-native" else work)
            if remote_server:
                shutil.rmtree(cache);cache.mkdir()
            transfer_start=len(remote_server.events) if remote_server else 0
            with (output/'cache.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                if identity is None:
                    store=ProtectedStore();sdk=DOTNET_ROOT.parents[1]
                    snap=store.snapshot(sdk,[Path('/nix/store')]);identity=digest(snap)
                projects=qualify(subject)
                before=tree_snapshot(subject,[subject])
                if root.exists():shutil.rmtree(root)
                root.mkdir();original={}
                for p in subject.rglob('*'):
                    if not p.is_file():continue
                    rel=str(p.relative_to(subject));data=p.read_bytes()
                    if 'obj' in Path(rel).parts:data=data.replace(str(subject).encode(),str(root).encode())
                    target=root/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);original[rel]=data
                if tree_snapshot(subject,[subject])!=before:raise ValueError('source changed while copying')
                shared=digest({p:input_hash(p,b,root) for p,b in original.items() if not p.endswith('.cs') and 'obj' not in Path(p).parts})
                nodes={}
                for project,deps in projects.items():
                    directory=str(Path(project).parent)+'/'
                    inputs={p:input_hash(p,b,root) for p,b in original.items() if p.startswith(directory)}
                    nodes[project]=dict(identity=digest(dict(shared=shared,inputs=inputs)),dependencies=deps)
                scratch=output/(label+'-scratch');scratch.mkdir()
                session=output/(label+'-session.json');event_path=output/(label+'-events.json')
                session.write_text(json.dumps(dict(workspace=str(root),cache=str(cache),scratch=str(scratch),report=str(event_path),entry=entry,remote=remote_server.url+"/native" if remote_server else None,toolchain=digest(dict(sdk=identity,sdkRevision=sdk_revision,plugin=hashlib.sha256(plugin.read_bytes()).hexdigest(),targets=targets.read_text(),controller={p:hashlib.sha256((ROOT/'tools'/p).read_bytes()).hexdigest() for p in ('probe_native_cache.py','discovery_contract.py','preparation_identity.py','protected_store.py')},environment={k:v.replace(str(root),'${WORKSPACE}') for k,v in cache_environment(output,root).items() if k!='NATIVE_CACHE_SESSION'})),files=[dict(path=p,hash=hashlib.sha256(b).hexdigest()) for p,b in original.items()],projects=nodes)))
                prep=time.perf_counter()-t
                build,log,_=run(label,command(root,True),root,dict(NATIVE_CACHE_SESSION=str(session)))
                events=json.loads(event_path.read_text())
                # Every build begins without compiler outputs; hits must be real.
                shutil.rmtree(scratch)
        else:build,log,_=run(label,command(root,False),root)
        elapsed=time.perf_counter()-t
        actual_compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
        _,actual,_=run(label+'-app',[dotnet,assembly(root)],output)
        assert actual.strip()==expected,(label,actual,expected)
        if compiles is not None:assert actual_compiles==compiles,(label,actual_compiles,compiles)
        sample=dict(mode=mode,label=label,seconds=elapsed,preparationSeconds=prep,buildSeconds=build,compiles=actual_compiles,hits=sum(e['kind']=='hit' for e in events),misses=sum(e['kind']=='miss' for e in events),rejected=sum(e['kind']=='rejected' for e in events),output=actual.strip(),runtimeDllHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in assembly(root).parent.glob('*.dll')})
        if remote_server and mode=='native':
            sample['http']=remote_server.totals(transfer_start)
            assert sum(e['kind']=='remote' and e['message']=='download' for e in events)==sample['hits'],'hit was not remotely recovered'
        report['samples'].append(sample);save();print(label,round(elapsed,3),actual_compiles,sample['hits'],flush=True)
        return sample
    try:
        elapsed,_,_=run('bootstrap',[dotnet,'build',ROOT/'tools/NativeProjectCache','-c','Release','--nologo'],ROOT);report['setup'].append(dict(tool='NativeProjectCache',seconds=elapsed))
        for label,root in [('source',subject),('ordinary',ordinary)]:
            elapsed,_,_=run('restore-'+label,[dotnet,'msbuild',entry,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo'],root);report['setup'].append(dict(restore=label,seconds=elapsed))
        measure('raw','cold-raw',oracle(spec['edges']),count)
        measure('native','cold-native',oracle(spec['edges']),count)
        assert report['samples'][-1]['runtimeDllHashes']==report['samples'][-2]['runtimeDllHashes'],'cold DLL mismatch'
        for case in ('warm','body'):
            for i in range(repetitions):
                if case=='body':
                    for root in (subject,ordinary):(root/'N0000/Value.cs').write_text(source(0,[],False).replace('1L',str(1+7*(i+1))+'L'))
                expected=str(int(oracle(spec['edges']))+(int(oracle(spec['edges'],0))-int(oracle(spec['edges'])))*(i+1)) if case=='body' else oracle(spec['edges'])
                for mode in (('native','raw') if i%2==0 else ('raw','native')):measure(mode,f'{case}-{i}-{mode}',expected,0 if case=='warm' else 1)
                assert report['samples'][-1]['runtimeDllHashes']==report['samples'][-2]['runtimeDllHashes'],'paired DLL mismatch'
        if extended and remote_server:
            expected=report['samples'][-1]['output']
            measure('native','relocated',expected,0,output/'another-consumer')
            for root in (subject,ordinary):
                p=root/'N0000/Value.cs';p.write_text(p.read_text().replace('public static long Read()', 'public static int AddedApi() => 42; public static long Read()'))
            measure('raw','api-raw',expected,3);measure('native','api-native',expected,3)
            events=json.loads((output/'api-native-events.json').read_text())
            key=next(e['key'] for e in events if e.get('project')=='N0000/N0000.csproj' and e['kind']=='miss')
            index='/native/index/'+key;blob='/native/cas/'+remote_server.data[index].decode()
            remote_server.data.pop(blob)
            measure('native','remote-missing-blob',expected,1)
            remote_server.data[blob]=b'corrupt'
            measure('native','remote-corrupt-blob',expected,1)
            # A valid CAS hash must not authorize archive traversal.
            import io, zipfile
            payload=io.BytesIO()
            with zipfile.ZipFile(payload,'w') as archive:archive.writestr('../escape','invalid')
            data=payload.getvalue();bad_hash=hashlib.sha256(data).hexdigest()
            remote_server.data[index]=bad_hash.encode();remote_server.data['/native/cas/'+bad_hash]=data
            measure('native','remote-invalid-archive',expected,1)
            assert not (cache/'escape').exists()
            p=subject/'N0000/Value.cs';valid=p.read_text();p.write_text('this is invalid C#')
            before_puts=sum(e['method']=='PUT' for e in remote_server.events)
            try:
                measure('native','remote-failed-build',expected)
                raise AssertionError('bad source accepted')
            except RuntimeError:pass
            assert sum(e['method']=='PUT' for e in remote_server.events)==before_puts,'failed build published remote entries'
            p.write_text(valid)
            report['failedBuildDidNotPublish']=True
            sdk_revision='changed-sdk-identity'
            measure('native','sdk-identity-change',expected,count)
            sdk_revision='original'
            remote_server.offline=True
            measure('native','remote-outage',expected,count)
            remote_server.offline=False
            measure('native','remote-recovery',expected,0)
            report['remoteFaultChecks']=True
        if extended and not remote_server:
            expected=report['samples'][-1]['output']
            measure('native','relocated',expected,0,output/'relocated')
            # Public API additions should rebuild the root and its direct consumers.
            for root in (subject,ordinary):
                p=root/'N0000/Value.cs';p.write_text(p.read_text().replace('public static long Read()', 'public static int AddedApi() => 42; public static long Read()'))
            measure('raw','api-raw',expected,3);measure('native','api-native',expected,3)
            # Source namespace membership must invalidate, even when the file is empty.
            (subject/'N0000/New.cs').write_text('// added source\n')
            measure('native','added-source',expected,1)
            (subject/'N0000/New.cs').unlink();measure('native','removed-source',expected,0)
            # Corrupt the exact root entry used by the API build, not an obsolete key.
            events=json.loads((output/'api-native-events.json').read_text());event=next(e for e in events if e['project']=='N0000/N0000.csproj' and e['kind']=='miss')
            (cache/event['key']/'artifacts/N0000/bin/Release/net10.0/N0000.dll').write_bytes(b'corrupt')
            sample=measure('native','corruption',expected,1);assert sample['rejected']==1
            # Configuration/import changes are conservatively shared inputs.
            p=subject/'Directory.Build.props';p.write_text(p.read_text().replace('</PropertyGroup>','<Nullable>enable</Nullable></PropertyGroup>'))
            measure('native','changed-props',expected,count)
            # Failed compilation must not publish any new cache entry.
            p=subject/'N0000/Value.cs';valid=p.read_text();p.write_text('this is invalid C#')
            before_entries=sorted(p.name for p in cache.iterdir())
            try:
                measure('native','failed-build',expected)
                raise AssertionError('bad source accepted')
            except RuntimeError:pass
            assert sorted(p.name for p in cache.iterdir())==before_entries,'failed build published entries'
            p.write_text(valid);measure('native','after-failure',expected,0)
            report['failedBuildDidNotPublish']=True
            # Custom targets are refused before MSBuild invocation.
            p=subject/'N0000/N0000.csproj';p.write_text(p.read_text().replace('</Project>','<Target Name="Sneaky"/></Project>'))
            try:qualify(subject);raise AssertionError('custom target accepted')
            except ValueError:report['customTargetRejected']=True
        report['accepted']=True
    except BaseException as error:report['failure']=dict(type=type(error).__name__,message=str(error));raise
    finally:
        if remote_server:
            report['remoteHttp']=remote_server.totals();report['delayMs']=remote_server.delay_ms
            report['scope']='isolated consumer workspaces and empty local caches, loopback HTTP; same host/SDK; no sandbox or cross-host qualification'
            (output/'http-events.json').write_text(json.dumps(remote_server.events,indent=2))
        save()
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--nodes',type=int,default=10);p.add_argument('--repetitions',type=int,default=2);p.add_argument('--no-extended',action='store_true')
    p.add_argument('--remote-probe',action='store_true');p.add_argument('--delay-ms',type=float,default=0)
    a=p.parse_args()
    if a.remote_probe:
        from probe_http_cache import CacheServer
        with CacheServer(a.delay_ms) as server:probe(a.output,a.nodes,a.repetitions,not a.no_extended,server)
    else:probe(a.output,a.nodes,a.repetitions,not a.no_extended)
