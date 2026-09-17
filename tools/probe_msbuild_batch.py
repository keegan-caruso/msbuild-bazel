"""Experimental whole-graph MSBuild action on an owned synthetic fixture only.

No graph exporter: declare the entire generated source namespace and normalized
restore payload. Not an arbitrary-project preparation API or remote qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

from prepare_graph import ROOT, DOTNET_ROOT
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream
from starlark import call
from synthetic_graph import generate, name, source, oracle


def probe(output, count, repetitions, imports):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    ordinary=output/'ordinary';subject=output/'source';g=output/'g';g.mkdir()
    spec=generate(ordinary,count,'fan');generate(subject,count,'fan');entry=spec['entry']
    dotnet=DOTNET_ROOT/'dotnet'
    report=dict(accepted=False,experimental=True,performanceQualified=False,count=count,samples=[],setup=[],
        scope='owned synthetic package-free fixture only; complete namespace copy plus build; restore and tool build excluded',
        sdkImports={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in imports})
    def save(): (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(label,command,cwd):
        t=time.perf_counter();r=subprocess.run(list(map(str,command)),cwd=cwd,env=cache_environment(output,cwd),capture_output=True,text=True,timeout=1200)
        elapsed=time.perf_counter()-t;(output/(label+'.log')).write_text(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError(label+' failed; see retained log')
        return elapsed,r.stdout+r.stderr
    startup=[BAZEL,'--max_idle_secs=120','--nohome_rc','--noworkspace_rc','--output_base='+str(output/'b'),'--output_user_root='+str(output/'u')]
    baseline=[dotnet,'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-graphBuild','-isolateProjects','-m:2','-nodeReuse:false','-nologo','-verbosity:normal']
    def prepare():
        # Fixture namespace is owned by this serial probe. Verify the copy against
        # a second complete content snapshot; no mutable bin/obj compiler state.
        def snapshot():
            return {str(p.relative_to(subject)):p.read_bytes() for p in subject.rglob('*') if p.is_file() and not {'bin','.nuget'}.intersection(p.relative_to(subject).parts)}
        before=snapshot();restore={};srcs=[]
        for relative,data in before.items():
            if 'obj' in Path(relative).parts:
                restore[relative]=data.decode().replace(str(subject),'${WORKSPACE}').replace(str(DOTNET_ROOT),'${SDK}')
            else:
                target=g/'src'/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists() or target.read_bytes()!=data:target.write_bytes(data)
                srcs.append('src/'+relative)
        if snapshot()!=before: raise RuntimeError('source changed while snapshotting')
        (g/'restore.json').write_text(json.dumps(restore,sort_keys=True))
        (g/'runner').mkdir(exist_ok=True)
        for suffix in ('.dll','.deps.json','.runtimeconfig.json'):
            shutil.copyfile(ROOT/f'tools/ActionRunner/bin/Release/net10.0/ActionRunner{suffix}',g/f'runner/ActionRunner{suffix}')
        shutil.copyfile(ROOT/'tools/ActionRunner/Build/Action.props',g/'runner/Action.props')
        (g/'runner/Batch.targets').write_text('<Project/>\n')
        for filename in ('msbuild.bzl','batch.bzl'):shutil.copyfile(ROOT/'bazel'/filename,g/filename)
        (g/'MODULE.bazel').write_text('module(name="msbuild_batch_probe")\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n'+call('local_dotnet_sdk',name='dotnet',path=str(DOTNET_ROOT),external_imports=list(map(str,imports))))
        (g/'host.json').write_text(json.dumps(dict(platform=platform.platform(),machine=platform.machine(),policyRevision=1)))
        (g/'BUILD.bazel').write_text('load(":batch.bzl", "msbuild_batch")\n'+call('msbuild_batch',name='batch',project=entry,srcs=sorted(srcs),restore=['restore.json'],
            plugin='runner/ActionRunner.dll',build_props='runner/Action.props',build_targets='runner/Batch.targets',runner='runner/ActionRunner.dll',runner_support=['runner/ActionRunner.deps.json','runner/ActionRunner.runtimeconfig.json'],host_identity='host.json',sdk='@dotnet//:files',dotnet='@dotnet//:sdk/dotnet'))
    def measure(mode,label,expected,compiled):
        t=time.perf_counter();prep=0
        if mode=='msbuild':
            build,log=run(label,baseline,ordinary);compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines())
            assembly=ordinary/name(count-1)/f'bin/Release/net10.0/{name(count-1)}.dll'
        else:
            prepare();prep=time.perf_counter()-t
            execution=output/(label+'-execution.json')
            build,_=run(label,[*startup,'build','//:batch','--disk_cache='+str(output/'cache'),'--jobs=2','--spawn_strategy=darwin-sandbox','--strategy=MsbuildBatch=darwin-sandbox','--noshow_progress','--color=no','--curses=no','--execution_log_json_file='+str(execution)],g)
            compiles=0
            for action in json_stream(execution):
                if action.get('mnemonic')=='MsbuildBatch' and not action.get('cacheHit'):
                    assert action['runner']=='darwin-sandbox'
                    compiles+=json.loads((g/'bazel-bin/batch.diagnostics/action.json').read_text())['compiles']
            assembly=g/f'bazel-bin/batch.bundle/app/{name(count-1)}.dll'
        elapsed=time.perf_counter()-t
        _,actual=run(label+'-app',[dotnet,assembly],output)
        assert actual.strip()==expected,(label,actual,expected)
        assert compiles==compiled,(label,compiles,compiled)
        report['samples'].append(dict(mode=mode,label=label,seconds=elapsed,preparationSeconds=prep,buildSeconds=build,compiles=compiles,output=actual.strip()));save();print(label,round(elapsed,3),compiles,flush=True)
    try:
        elapsed,_=run('bootstrap',[dotnet,'build',ROOT/'tools/ActionRunner','-c','Release','--nologo'],ROOT);report['setup'].append(dict(tool='ActionRunner',seconds=elapsed))
        for label,path in [('ordinary',ordinary),('source',subject)]:
            elapsed,_=run('restore-'+label,[dotnet,'msbuild',entry,'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo'],path)
            report['setup'].append(dict(restore=label,seconds=elapsed))
            for assets in path.rglob('project.assets.json'):
                assert all(v['type']=='project' for v in json.loads(assets.read_text())['libraries'].values())
        for mode in ('msbuild','batch'):measure(mode,'fresh-'+mode,oracle(spec['edges']),count)
        for case in ('warm','shared'):
            for index in range(repetitions):
                if case=='shared':
                    for path in (ordinary,subject):(path/'N0000/Value.cs').write_text(source(0,[],False).replace('1L',str(1+7*(index+1))+'L'))
                expected=str(int(oracle(spec['edges']))+(int(oracle(spec['edges'],0))-int(oracle(spec['edges'])))*(index+1)) if case=='shared' else oracle(spec['edges'])
                for mode in (('msbuild','batch') if index%2 else ('batch','msbuild')):measure(mode,f'{case}-{index}-{mode}',expected,0 if case=='warm' else count if mode=='batch' else 1)
        report['medians']={case:{mode:statistics.median(s['seconds'] for s in report['samples'] if s['label'].startswith(case+'-') and s['mode']==mode) for mode in ('msbuild','batch')} for case in ('fresh','warm','shared')}
        report['accepted']=True
    except BaseException as error:report['failure']=str(error);raise
    finally:
        if (g/'BUILD.bazel').exists():run('shutdown',[*startup,'shutdown'],g)
        save()
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--nodes',type=int,default=100);p.add_argument('--repetitions',type=int,default=3);p.add_argument('--sdk-import',type=Path,action='append',default=[])
    a=p.parse_args();probe(a.output,a.nodes,a.repetitions,a.sdk_import)
