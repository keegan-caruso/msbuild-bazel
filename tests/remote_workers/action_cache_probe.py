"""Fresh-consumer HTTP action-cache qualification against pinned bazel-remote."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import statistics
from cache_service import CacheService, PIN
from workload import fixture, native, mutate, raw, remove, shutdown, ROOT


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),scope='same-host fresh consumers; not independent-worker proof',service=PIN,harnessSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},cases=[])
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        for kind in args.workloads:
            root=output/kind;root.mkdir()
            with CacheService(args.cache_binary,root/'server') as server:
                def build(label,snapshot=None,edit=None,upload=True,action=True):
                    base=root/label;source=fixture(base,kind,args.packages,args.checkout)
                    if edit:mutate(source,kind,edit)
                    if edit in ('failed-test','lease-mutation'):
                        mutate(source,kind,'body')
                        value=source/'src/Serilog/Log.cs';value.write_bytes(value.read_bytes()+('\n// '+edit+' cache publication control\n').encode())
                    try:
                        value=native(base,source,kind,args.packages,server.url+'/native',snapshot,
                                     failed=edit in ('failed-test','lease-mutation'),lease_mutation=edit=='lease-mutation',install_cache=args.bazel_install_cache,
                                     repository_cache=args.bazel_repository_cache,action_cache=server.url if action else None,action_upload=upload if action else False)
                    finally:shutdown(base)
                    report['cases'].append(dict(kind=kind,case=label,result=value));save()
                    print(kind,label,value['accepted'],value.get('buildActions'),value.get('remoteBuildHits'),value.get('compiles'),round(value['wallSeconds'],3),flush=True)
                    return value
                producer=build('producer');key=producer['remote']['publishedSnapshot'];remove(root/'producer')
                # Seeds are real inputs: prime the full-seed variant independently.
                primer=build('seeded-primer',key);assert primer['buildActions']==1 and primer['compiles']==0
                remove(root/'seeded-primer')
                for repetition in range(args.repetitions):
                    # Pair outer-hit/inner-only comparisons, alternating their order.
                    values={}
                    for mode in (('outer','inner') if repetition%2==0 else ('inner','outer')):
                        value=build(mode+'-'+str(repetition),key,upload=False,action=mode=='outer');values[mode]=value
                        assert value['buildActions']==(0 if mode=='outer' else 1) and value['compiles']==0,value
                        assert value['remoteBuildHits']==(1 if mode=='outer' else 0)
                        assert value['managedHashes']==producer['managedHashes']
                        if kind=='serilog':assert value['testActions']==1 and value['test']['passed']
                    # Read-only changed actions remain misses on every repetition.
                    changed=build('body-miss-'+str(repetition),key,'body',upload=False)
                    assert changed['buildActions']==1 and changed['compiles']==1
                    raw_base=root/('raw-'+str(repetition));raw_source=fixture(raw_base,kind,args.packages,args.checkout)
                    raw(raw_base,raw_source,kind,args.packages,label='warmup',test=False)
                    ordinary=raw(raw_base,raw_source,kind,args.packages,label='unchanged')
                    assert ordinary['compiles']==0
                    assert ordinary['managedHashes']==values['outer']['managedHashes']
                    mutate(raw_source,kind,'body');edited=raw(raw_base,raw_source,kind,args.packages,label='body')
                    assert edited['compiles']>=1
                    assert edited['managedHashes']==changed['managedHashes']
                    report.setdefault('comparisons',[]).append(dict(kind=kind,repetition=repetition,
                        outer=values['outer']['wallSeconds'],inner=values['inner']['wallSeconds'],bodyMiss=changed['wallSeconds'],
                        raw=ordinary['seconds'],rawBody=edited['seconds'],managedHashesEqual=True))
                    save()
                changed=build('body',key,'body');assert changed['buildActions']==1 and changed['compiles']==1
                changed_hit=build('body-hit',key,'body',upload=False)
                assert changed_hit['buildActions']==0 and changed_hit['remoteBuildHits']==1
                assert changed_hit['managedHashes']==changed['managedHashes']
                if kind=='serilog':
                    def puts():
                        return sum(float(line.rsplit(' ',1)[1]) for line in server.read('/metrics').decode().splitlines()
                                   if line.startswith('http_request_duration_seconds_count{') and 'method="PUT"' in line)
                    for rejection in ('failed-test','lease-mutation'):
                        before=puts()
                        failed=build(rejection,key,rejection)
                        assert failed['actionCache']['stagedObjects']>0
                        assert failed['actionCache']['publishedObjects']==0
                        assert failed['remote']['transport']['putRequests']==0
                        assert puts()==before, 'rejected invocation wrote to the real service'
                        assert not (root/rejection/'state/cache').exists()
                        assert not (root/rejection/'state/pending').exists()
                server.capture('final')
        report['medians']=[dict(kind=kind,**{key:statistics.median(c[key] for c in report['comparisons'] if c['kind']==kind)
                            for key in ('outer','inner','bodyMiss','raw','rawBody')}) for kind in args.workloads]
        report['accepted']=True
    finally:save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('output','cache-binary','packages','checkout','bazel-install-cache','bazel-repository-cache'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--workloads',nargs='+',choices=['diamond','serilog'],default=['diamond','serilog'])
    p.add_argument('--repetitions',type=int,default=3)
    run(p.parse_args())
