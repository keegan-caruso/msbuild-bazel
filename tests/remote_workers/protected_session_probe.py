"""Compare default, one-shot protected store, and warm protected controller sessions."""
import argparse
import json
import statistics
import subprocess
from pathlib import Path
from cache_service import CacheService
from workload import ROOT,SDK,fixture,native,mutate,raw,remove,shutdown


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,samples=[],controls=[],revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for kind in ['diamond','serilog']:
            root=out/kind;root.mkdir()
            with CacheService(a.cache_binary,root/'server') as server:
                err=(root/'session.stderr').open('w')
                session=subprocess.Popen([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'workflow-session'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,text=True,bufsize=1)
                def invoke(base,source,key=None,mode='session',upload=False,failed=False,lease=False):
                    return native(base,source,kind,a.packages,server.url+'/native',key,install_cache=a.bazel_install_cache,repository_cache=a.bazel_repository_cache,action_cache=server.url,action_upload=upload,trust_store=mode!='default',session=session if mode=='session' else None,failed=failed,lease_mutation=lease)
                try:
                    producer=root/'producer';source=fixture(producer,kind,a.packages,a.checkout)
                    try:p=invoke(producer,source,upload=True)
                    finally:shutdown(producer)
                    assert p['protectedStore']['roots']>0 and p['protectedStore']['hits']>0,p.get('protectedStore')
                    key=p['remote']['publishedSnapshot'];expected=p['managedHashes'];report['controls'].append(dict(kind=kind,case='cold-session-producer',result=p));remove(producer);save()
                    base=root/'consumer';source=fixture(base,kind,a.packages,a.checkout)
                    try:
                        first=invoke(base,source,key);assert first['remoteBuildHits']==1
                        (base/'result').rename(base/'initial-result')
                        for rep in range(3):
                            for mode in (['default','oneshot','session'] if rep%2==0 else ['session','oneshot','default']):
                                v=invoke(base,source,key,mode)
                                assert v['managedHashes']==expected and v['compiles']==0 and v['worker']==first['worker']
                                if mode=='session':assert v['protectedStore']['fullScans']==first['protectedStore']['fullScans'] and v['protectedStore']['hits']>=2*v['protectedStore']['roots']
                                if mode=='oneshot':assert v['protectedStore']['fullScans']>0 and v['protectedStore']['hits']>0
                                report['samples'].append(dict(kind=kind,mode=mode,repetition=rep,result=v));save()
                                print(kind,mode,rep,round(v['wallSeconds'],3),v.get('protectedStore'),flush=True)
                                (base/'result').rename(base/f'result-{rep}-{mode}')
                        mutate(source,kind,'body');edited=invoke(base,source,key)
                        rb=root/'raw';rs=fixture(rb,kind,a.packages,a.checkout);mutate(rs,kind,'body');oracle=raw(rb,rs,kind,a.packages)
                        assert edited['compiles']==1 and edited['managedHashes']==oracle['managedHashes']
                        report['controls'].append(dict(kind=kind,case='body-edit',result=edited));save()
                    finally:shutdown(base)
                    if kind=='serilog':
                        def puts():return sum(float(l.rsplit(' ',1)[1]) for l in server.read('/metrics').decode().splitlines() if l.startswith('http_request_duration_seconds_count{') and 'method="PUT"' in l)
                        for rejection in ['failed-test','lease-mutation']:
                            b=root/rejection;s=fixture(b,kind,a.packages,a.checkout);mutate(s,kind,'body')
                            if rejection=='failed-test':mutate(s,kind,'failed-test')
                            log=s/'src/Serilog/Log.cs';log.write_bytes(log.read_bytes()+('\n// '+rejection+' protected session control\n').encode())
                            before=puts()
                            try:v=invoke(b,s,key,upload=True,failed=True,lease=rejection=='lease-mutation')
                            finally:shutdown(b)
                            assert v['actionCache']['stagedObjects']>0 and v['actionCache']['publishedObjects']==0 and v['remote']['transport']['putRequests']==0 and puts()==before
                            report['controls'].append(dict(kind=kind,case=rejection,result=v));save()
                finally:
                    session.stdin.close()
                    try:session.wait(timeout=15)
                    except subprocess.TimeoutExpired:session.kill();session.wait()
                    err.close()
                server.capture('final')
        report['medians']=[dict(kind=kind,mode=mode,**{k:statistics.median(s['result']['wallSeconds'] if k=='wall' else s['result']['phases'][k] for s in report['samples'] if s['kind']==kind and s['mode']==mode) for k in ['wall','identity','leaseExit']}) for kind in ['diamond','serilog'] for mode in ['default','oneshot','session']]
        report['accepted']=True
    finally:save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['output','cache-binary','packages','checkout','bazel-install-cache','bazel-repository-cache']:p.add_argument('--'+n,type=Path,required=True)
    run(p.parse_args())
