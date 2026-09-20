"""Bootstrap raw Orchard MSBuild, then measure three clean entry-only builds."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time


def run(a):
    source=a.output/'source';feed=a.output/'feed'
    if not a.reuse_bootstrap:
        a.output.mkdir(parents=True,exist_ok=False)
        source.mkdir();feed.mkdir()
        with tarfile.open(a.source_archive) as t:t.extractall(source)
        with tarfile.open(a.feed_archive) as t:t.extractall(feed)
    else:
        assert (source/'src/OrchardCore.Cms.Web/obj/project.assets.json').is_file()
        index=1
        while (a.output/f'previous-{index}').exists():index+=1
        prior=a.output/f'previous-{index}';prior.mkdir(exist_ok=False)
        for path in a.output.iterdir():
            if path.is_file():path.rename(prior/path.name)
    if a.adapter_request is not None:
        if a.adapter_execroot is None:raise ValueError('adapter-execroot is required with adapter-request')
        request=json.loads(a.adapter_request.read_text())
        for item in request['sources']:
            contents=(a.adapter_execroot/item['source']).read_bytes()
            destination=source/item['destination']
            if not destination.exists() or destination.read_bytes()!=contents:
                if a.reuse_bootstrap and not item['destination'].startswith('src/OrchardCore.Cms.Web/'):
                    raise ValueError('Dependency/configuration input differs; use a fresh bootstrap: '+item['destination'])
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(contents)
        (a.output/'source-comparison.json').write_text(json.dumps(dict(matchedAdapterInputs=len(request['sources']),adapterRequest=str(a.adapter_request)))+'\n')
    env=dict(os.environ,DOTNET_ROOT=str(a.dotnet.parent),DOTNET_CLI_HOME=str(a.output/'home'),NUGET_PACKAGES=str(a.output/'packages'),MSBuildEnableWorkloadResolver='false',DOTNET_EnableDiagnostics='0',DOTNET_CLI_TELEMETRY_OPTOUT='1')
    entry='src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj'
    common=[str(a.dotnet),'msbuild',entry,'-t:Build','-p:Configuration=Release','-p:TargetFramework=net10.0','-p:UseSharedCompilation=false','-nodeReuse:false','-nologo']
    def build(name,args):
        start=time.perf_counter()
        with (a.output/(name+'.log')).open('w') as log:p=subprocess.run(common+args,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
        result=dict(case=name,seconds=time.perf_counter()-start,exitCode=p.returncode)
        print(json.dumps(result),flush=True)
        if p.returncode:raise RuntimeError(name+' failed')
        return result
    records=[] if a.reuse_bootstrap else [build('bootstrap',['-restore','-p:RestoreSources='+str(feed),'-p:NuGetAudit=false','-m:2'])]
    for index in range(3):
        for folder in ['bin','obj/Release']:shutil.rmtree(source/Path(entry).parent/folder,ignore_errors=True)
        records.append(build('entry-'+str(index),['-p:BuildProjectReferences=false','-m:1','-verbosity:normal','-clp:PerformanceSummary','-bl:'+str(a.output/f'entry-{index}.binlog')+';ProjectImports=None']))
        records[-1]['compileInvocations']=(a.output/f'entry-{index}.log').read_text().count(' /noconfig ')
        assert records[-1]['compileInvocations']==1
        (a.output/'report.json').write_text(json.dumps(records,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source-archive','feed-archive','output','dotnet']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reuse-bootstrap',action='store_true')
    p.add_argument('--adapter-request',type=Path)
    p.add_argument('--adapter-execroot',type=Path)
    run(p.parse_args())
