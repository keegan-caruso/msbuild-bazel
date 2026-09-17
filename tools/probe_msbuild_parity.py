"""Time complete leased preparation + entry build versus ordinary MSBuild.

Acquisition/restore are setup. Native application execution is an untimed correctness
oracle after every build. This uses one persistent Bazel server and an explicitly
trusted Nix store session. No result is a remote-cache or platform qualification.
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


def probe(output, count, repetitions, split=True):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    ordinary=output/'ordinary';subject=output/'source';generated=output/'g'
    spec=generate(ordinary,count,'fan');generate(subject,count,'fan')
    entry=spec['entry'];edges=spec['edges'];dotnet=DOTNET_ROOT/'dotnet'
    report=dict(accepted=False,count=count,repetitions=repetitions,compileBoundary=split,
        performanceQualified=False,scope='full preparation and Build including lease teardown; restore and app oracle excluded',
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
        if mode=='msbuild':
            elapsed,log=run(label,baseline,ordinary)
            compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
            record=dict(mode=mode,seconds=elapsed,buildSeconds=elapsed,compiles=compiles)
            assembly=ordinary/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
        else:
            if generated.exists():shutil.rmtree(generated)
            t=time.perf_counter()
            with prepared_view(subject,output/'state',generated,entries,protected_store=store,incremental_sources=True,
                               compile_boundary=split) as work:
                prep=time.perf_counter()-t
                execution=output/(label+'-execution.json')
                build,_=run(label,[*startup,'build','//:all','--disk_cache='+str(output/'cache'),'--jobs=2',
                    '--spawn_strategy=darwin-sandbox','--strategy=MsbuildProject=darwin-sandbox',
                    '--noshow_progress','--color=no','--curses=no','--execution_log_json_file='+str(execution),
                    '--profile='+str(output/(label+'-profile.json.gz'))],generated)
            elapsed=time.perf_counter()-t
            compiles=0
            for action in json_stream(execution):
                if action.get('mnemonic')=='MsbuildProject' and not action.get('cacheHit'):
                    identity=action['targetLabel'].split(':node_')[-1]
                    detail=json.loads((generated/f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
                    assert len(detail['compiledProjects'])==1 and action['runner']=='darwin-sandbox'
                    compiles+=len(detail['compiledProjects'])
            graph=json.loads((generated/'graph.json').read_text())
            node=next(n for n in graph['nodes'] if n['project']=='workspace/'+entry)
            assembly=generated/f'bazel-bin/node_{node["id"]}.bundle/artifacts'/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
            record=dict(mode=mode,seconds=elapsed,preparationReadySeconds=prep,buildSeconds=build,teardownSeconds=elapsed-prep-build,work=work,compiles=compiles)
        _,actual=run(label+'-app',[dotnet,assembly],output)
        assert actual.strip()==expected,(label,actual,expected)
        assert compiles==expected_compiles,(label,compiles,expected_compiles)
        record.update(label=label,output=actual.strip())
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
        report['medians']={case:{mode:statistics.median(s['seconds'] for s in report['samples'] if s['label'].startswith(case+'-') and s['mode']==mode) for mode in ('msbuild','adapter')} for case in ('fresh','warm','shared')}
        report['accepted']=True
    except BaseException as error:
        report['failure']=dict(type=type(error).__name__,message=str(error));raise
    finally:
        if generated.exists():run('shutdown',[*startup,'shutdown'],generated)
        save()
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--nodes',type=int,default=100)
    parser.add_argument('--repetitions',type=int,default=5);parser.add_argument('--legacy',action='store_true')
    args=parser.parse_args();probe(args.output,args.nodes,args.repetitions,not args.legacy)
