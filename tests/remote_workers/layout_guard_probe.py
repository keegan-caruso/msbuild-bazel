"""A stale portable layout must fail without publishing any action-cache objects."""
import argparse
import json
from pathlib import Path
import subprocess
from cache_service import CacheService
from workload import ROOT, SDK, BAZEL, fixture, shutdown


def run(a):
    root=a.output.resolve();root.mkdir(parents=True,exist_ok=False)
    source=fixture(root/'worker','diamond',a.packages)
    layout=json.loads(a.layout.read_text());layout['projects'][layout['entry']]['dependencies']=[]
    path=root/'layout.json';path.write_text(json.dumps(layout))
    with CacheService(a.cache_binary,root/'server') as server:
        request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(source),state=str(root/'worker/state'),output=str(root/'worker/result'),entry=layout['entry'],operation='build',**{'nuget-packages':str(a.packages),'project-actions':True,'project-layout':str(path),'bazel-remote-cache':server.url,'bazel-remote-upload':True,'bazel-install-cache':str(a.bazel_install_cache),'bazel-repository-cache':str(a.bazel_repository_cache)})
        request_path=root/'request.json';request_path.write_text(json.dumps(request))
        try:
            result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(request_path)],cwd=ROOT,capture_output=True,text=True,timeout=300)
            (root/'command.log').write_text(result.stdout+result.stderr)
            report=json.loads((root/'worker/result/report.json').read_text())
            assert result.returncode!=0 and not report['accepted']
            assert report['actionCache']['publishedObjects']==0 and report['MsbuildValidateLayout']['executed']==1
            assert 'Project layout differs from MSBuild discovery' in (root/'worker/result/bazel.log').read_text()
            puts=sum(float(line.rsplit(' ',1)[1]) for line in server.read('/metrics').decode().splitlines() if line.startswith('http_request_duration_seconds_count{') and 'method="PUT"' in line)
            assert puts==0
            (root/'report.json').write_text(json.dumps(dict(accepted=True,externalPuts=puts,workflow=report),indent=2)+'\n')
            print('Stale layout rejected; zero external PUTs',flush=True)
        finally:shutdown(root/'worker')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['output','layout','cache-binary','packages','bazel-install-cache','bazel-repository-cache']:parser.add_argument('--'+name,type=Path,required=True)
    run(parser.parse_args())
