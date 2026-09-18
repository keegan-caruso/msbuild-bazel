"""Real build controls for worker-qualified cache identities (same-host only)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from probe_http_cache import CacheServer
from synthetic_graph import generate, oracle

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])

def remove(path):
    if path.exists():
        for directory,_,_ in os.walk(path):os.chmod(directory,0o700)
        shutil.rmtree(path)

def run(output):
    output.mkdir(parents=True,exist_ok=False);report=dict(accepted=False,cases=[],scope='same-host identity controls')
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    def fixture(base):
        base.mkdir();source=base/'source';graph=generate(source,4,'fan')
        props=source/'Directory.Build.props';props.write_text(props.read_text().replace('TargetFramework>', 'TargetFrameworks>'))
        result=subprocess.run([str(SDK/'dotnet'),'msbuild',graph['entry'],'-t:Restore','-p:Configuration=Release','-p:TargetFramework=net10.0','-nologo'],cwd=source,capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        return source,graph
    def invoke(base,source,entry,endpoint,key=None):
        request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(source),state=str(base/'state'),entry=entry,output=str(base/'result'),operation='build',reuse=True,**{'independent-workers':True,'remote-endpoint':endpoint})
        if key:request['remote-snapshot']=key
        path=base/'request.json';path.write_text(json.dumps(request));result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'workflow','--request',str(path)],capture_output=True,text=True,timeout=600)
        (base/'command.log').write_text(result.stdout+result.stderr);assert result.returncode==0,result.stderr
        value=json.loads((base/'result/report.json').read_text());assert value['accepted'],value
        app=base/'state/g/bazel-bin/build.bundle/app/N0003.dll'
        actual=subprocess.check_output([str(SDK/'dotnet'),str(app)],text=True).strip();assert actual==oracle(graph['edges']),actual
        subprocess.run([str(BAZEL),'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base='+str(base/'state/b'),'--output_user_root='+str(base/'state/u'),'shutdown'],cwd=base/'state/g',capture_output=True,check=True)
        return value
    try:
        with CacheServer() as server:
            source,graph=fixture(output/'producer');producer=invoke(output/'producer',source,graph['entry'],server.url+'/native');assert producer['workerCacheEligible'],producer
            assert producer['compiles']==4;key=producer['remote']['publishedSnapshot'];catalog=json.loads(server.data['/native/cas/'+key]);original=server.data.copy();report['producer']=producer
            remove(output/'producer')
            for label in ('compatible','os-build','sdk-closure','bazel','legacy','unqualified'):
                base=output/label;source,graph=fixture(base)
                with server.lock:server.data=original.copy()
                selected=key
                if label not in ('compatible','unqualified'):
                    altered=json.loads(json.dumps(catalog))
                    if label=='os-build':altered['worker']['execution']['osBuild']='different'
                    elif label=='sdk-closure':altered['worker']['controllerSdkClosure']='f'*64
                    elif label=='bazel':altered['worker']['systemTools']['bazel']='e'*64
                    else:del altered['worker']
                    data=json.dumps(altered).encode();selected=hashlib.sha256(data).hexdigest();server.data['/native/cas/'+selected]=data
                if label=='unqualified':
                    # This literal property is harmless to Build, but outside the discovery grammar.
                    path=source/'Directory.Build.props';path.write_text(path.read_text().replace('<PropertyGroup>','<PropertyGroup><WorkerUnqualifiedProperty>true</WorkerUnqualifiedProperty>',1))
                before=len(server.events);value=invoke(base,source,graph['entry'],server.url+'/native',selected);events=server.events[before:]
                if label=='compatible':assert value['compiles']==0 and value['preparation']['reused'],value
                elif label=='unqualified':
                    assert value['compiles']==4 and not value['workerCacheEligible'] and 'publicationSkipped' in value['remote'],value
                    assert not any(e['method']=='PUT' for e in events)
                else:
                    assert value['compiles']==4 and 'snapshotMiss' in value['remote'],value
                    gets=[e for e in events if e['method']=='GET'];assert len(gets)==1,gets
                report['cases'].append(dict(case=label,result=value,transport=server.totals(before)));save();print(label,value['compiles'],flush=True)
            report['accepted']=True
    finally:save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);run(parser.parse_args().output.resolve())
