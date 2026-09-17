"""Owned loopback HTTP remote-cache comparison with fresh Bazel output bases.

Acquisition/restore are setup. Native application execution is an untimed correctness
oracle after every build. This uses one persistent Bazel server and an explicitly
trusted Nix store session. This tests loopback transfer only, not independent hosts or a production service.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time

from prepare_graph import ROOT, DOTNET_ROOT
from preparation_reuse import prepared_view
from protected_store import ProtectedStore
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream
from synthetic_graph import generate, name, source, oracle


def probe(output, count, repetitions, split=True, remote_server=None):
    if remote_server is None: raise ValueError("owned HTTP server required")
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    ordinary=output/'ordinary';subject=output/'source';generated=output/'g'
    spec=generate(ordinary,count,'fan');generate(subject,count,'fan')
    entry=spec['entry'];edges=spec['edges'];dotnet=DOTNET_ROOT/'dotnet'
    report=dict(accepted=False,count=count,repetitions=repetitions,compileBoundary=split,
        performanceQualified=False,scope='fresh Bazel output bases and generated workspaces with loopback HTTP; shared prepared-input session; same host only',
        samples=[],setup=[],sourceHashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*(ROOT/'tools').glob('*.py'),*(ROOT/'tools/ActionRunner').rglob('*.cs'),ROOT/'bazel/graph.bzl'] if not {'bin','obj'}.intersection(p.relative_to(ROOT).parts)})
    def save(): (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(label,command,cwd):
        t=time.perf_counter();r=subprocess.run(list(map(str,command)),cwd=cwd,env=cache_environment(output,cwd),capture_output=True,text=True,timeout=1800)
        elapsed=time.perf_counter()-t;(output/(label+'.log')).write_text(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError(label+' failed; see retained log')
        return elapsed,r.stdout+r.stderr
    startup=[BAZEL,'--max_idle_secs=120','--nohome_rc','--noworkspace_rc','--output_base='+str(output/'b'),'--output_user_root='+str(output/'u')]
    store=ProtectedStore()
    entries=[dict(project=entry,globalProperties={'Configuration':'Release','TargetFramework':'net10.0'})]
    baseline=[dotnet,'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-graphBuild','-isolateProjects','-m:2','-nodeReuse:false','-nologo','-verbosity:normal']
    def measure(mode,label,expected,expected_compiles):
        nonlocal generated, startup
        transfer_start=len(remote_server.events)
        if mode=='msbuild':
            elapsed,log=run(label,baseline,ordinary)
            compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
            record=dict(mode=mode,seconds=elapsed,buildSeconds=elapsed,compiles=compiles)
            assembly=ordinary/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
        else:
            generated=output/(label+'-g')
            startup=[BAZEL,'--max_idle_secs=10','--nohome_rc','--noworkspace_rc','--output_base='+str(output/(label+'-b')),'--output_user_root='+str(output/'u')]
            if generated.exists():shutil.rmtree(generated)
            t=time.perf_counter()
            with prepared_view(subject,output/'state',generated,entries,protected_store=store,incremental_sources=True,
                               compile_boundary=split) as work:
                # Only this owned generated workspace opts into HTTP remote caching.
                # Compiler actions remain native sandboxed with networking blocked.
                for rule in ('graph.bzl','msbuild.bzl'):
                    p=generated/rule
                    if p.exists():p.write_text(p.read_text().replace('"no-remote": "1"','"no-remote-exec": "1"'))
                prep=time.perf_counter()-t
                execution=output/(label+'-execution.json')
                build,_=run(label,[*startup,'build','//:all','--remote_cache='+remote_server.url+'/bazel','--noremote_cache_async','--remote_download_outputs=toplevel','--jobs=2',
                    '--spawn_strategy=darwin-sandbox','--strategy=MsbuildProject=darwin-sandbox',
                    '--noshow_progress','--color=no','--curses=no','--execution_log_json_file='+str(execution),
                    '--profile='+str(output/(label+'-profile.json.gz'))],generated)
            elapsed=time.perf_counter()-t
            compiles=0
            actions=[]
            for action in json_stream(execution):
                if action.get('mnemonic') in ('MsbuildProject','MsbuildRuntime'):actions.append(dict(mnemonic=action['mnemonic'],hit=action.get('cacheHit',False),runner=action.get('runner')))
                if action.get('mnemonic')=='MsbuildProject' and not action.get('cacheHit'):
                    identity=action['targetLabel'].split(':node_')[-1]
                    detail=json.loads((generated/f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
                    assert len(detail['compiledProjects'])==1 and action['runner']=='darwin-sandbox'
                    compiles+=len(detail['compiledProjects'])
            graph=json.loads((generated/'graph.json').read_text())
            node=next(n for n in graph['nodes'] if n['project']=='workspace/'+entry)
            assembly=generated/f'bazel-bin/node_{node["id"]}.bundle/artifacts'/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
            record=dict(mode=mode,seconds=elapsed,actions=actions,http=remote_server.totals(transfer_start),preparationReadySeconds=prep,buildSeconds=build,teardownSeconds=elapsed-prep-build,work=work,compiles=compiles)
        _,actual=run(label+'-app',[dotnet,assembly],output)
        assert actual.strip()==expected,(label,actual,expected)
        assert compiles==expected_compiles,(label,compiles,expected_compiles)
        if mode=='adapter':run(label+'-shutdown',[*startup,'shutdown'],generated)
        record.update(label=label,output=actual.strip(),runtimeDllHashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in assembly.parent.glob('*.dll')})
        if mode=='adapter':
            assert all(a['runner']=='remote cache hit' for a in actions if a['hit'])
            if label.startswith('warm-'):
                seed=next(s for s in report['samples'] if s['label']=='fresh-adapter')
                assert record['runtimeDllHashes']==seed['runtimeDllHashes']
        report['samples'].append(record);save();print(label,round(elapsed,3),compiles,flush=True)
    try:
        for tool in ('GraphExport','EvaluationProbe','ReplayPlugin','ActionRunner'):
            elapsed,_=run('bootstrap-'+tool,[dotnet,'build',ROOT/'tools'/tool,'-c','Release','--nologo'],ROOT)
            report['setup'].append(dict(tool=tool,seconds=elapsed))
        for label,path in [('ordinary',ordinary),('source',subject)]:
            elapsed,_=run('restore-'+label,[dotnet,'msbuild',entry,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo'],path)
            report['setup'].append(dict(restore=label,seconds=elapsed))
        for mode in ('msbuild','adapter'):measure(mode,'fresh-'+mode,oracle(edges),count)
        for case in ('warm','shared'):
            for index in range(repetitions):
                changed=case=='shared'
                if case=='shared':
                    for path in (ordinary,subject): (path/'N0000/Value.cs').write_text(source(0,[],False).replace('1L', str(1+7*(index+1))+'L'))
                expected=str(int(oracle(edges))+(int(oracle(edges,0))-int(oracle(edges)))*(index+1)) if changed else oracle(edges)
                for mode in (('msbuild','adapter') if index%2 else ('adapter','msbuild')):
                    measure(mode,f'{case}-{index}-{mode}',expected,0 if case=='warm' else 1 if split or mode=='msbuild' else count)
        for path in (ordinary,subject):
            p=path/'N0000/Value.cs';p.write_text(p.read_text().replace('public static long Read()', 'public static int AddedApi() => 42; public static long Read()'))
        measure('msbuild','api-msbuild',expected,3)
        measure('adapter','api-adapter',expected,count)
        report['medians']={case:{mode:statistics.median(s['seconds'] for s in report['samples'] if s['label'].startswith(case+'-') and s['mode']==mode) for mode in ('msbuild','adapter')} for case in ('fresh','warm','shared')}
        report['accepted']=True
    except BaseException as error:
        report['failure']=dict(type=type(error).__name__,message=str(error));raise
    finally:
        report['remoteHttp']=remote_server.totals();report['delayMs']=remote_server.delay_ms
        (output/'http-events.json').write_text(json.dumps(remote_server.events,indent=2))
        save()
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--nodes',type=int,default=100)
    parser.add_argument('--repetitions',type=int,default=5);parser.add_argument('--legacy',action='store_true')
    parser.add_argument('--delay-ms',type=float,default=0)
    args=parser.parse_args()
    from probe_http_cache import CacheServer
    with CacheServer(args.delay_ms) as server:probe(args.output,args.nodes,args.repetitions,not args.legacy,server)
