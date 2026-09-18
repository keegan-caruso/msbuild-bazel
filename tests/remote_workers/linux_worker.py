"""One side of Linux VM worker qualification; host orchestrator deletes producer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
from workload import fixture, native, mutate, raw, shutdown


def run(args):
    output=args.output;output.mkdir(parents=True,exist_ok=False)
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    report=dict(accepted=False,bootIdHash=hashlib.sha256(boot.encode()).hexdigest(),role=args.role,cases=[])
    handoff=json.loads(args.handoff.read_text()) if args.handoff else None
    if handoff:
        assert report['bootIdHash']!=handoff['bootIdHash'], 'Workers must have different VM boots'
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        for kind in args.workloads:
            def build(label,snapshot=None,edit=None,outer=True,upload=False):
                base=output/(kind+'-'+label);source=fixture(base,kind,args.packages,args.checkout)
                if edit:mutate(source,kind,edit)
                if edit=='failed-test':
                    mutate(source,kind,'body')
                    value=source/'src/Serilog/Log.cs';value.write_text(value.read_text()+'\n// failed Linux publication control\n')
                try:
                    value=native(base,source,kind,args.packages,args.endpoint+'/native',snapshot,
                                 action_cache=args.endpoint if outer else None,action_upload=upload,
                                 failed=edit=='failed-test')
                finally:shutdown(base)
                report['cases'].append(dict(kind=kind,case=label,result=value));save()
                print(kind,label,value.get('compiles'),value.get('remoteBuildHits'),flush=True)
                return value
            if args.role=='produce':
                producer=build('cold',upload=True);snapshot=producer['remote']['publishedSnapshot']
                assert producer['compiles']==(4 if kind=='diamond' else 2)
                primer=build('primer',snapshot,upload=True)
                assert primer['buildActions']==0 and primer['compiles']==0 and primer['remoteBuildHits']==1
                report.setdefault('handoff',{})[kind]=dict(snapshot=snapshot,worker=producer['worker'],managedHashes=producer['managedHashes'])
            else:
                source=handoff['handoff'][kind];snapshot=source['snapshot']
                recovered=build('outer',snapshot)
                assert recovered['worker']==source['worker']
                assert recovered['managedHashes']==source['managedHashes']
                assert recovered['remoteBuildHits']==1 and recovered['buildActions']==0 and recovered['compiles']==0
                inner=build('inner',snapshot,outer=False)
                assert inner['compiles']==0 and inner['buildActions']==1
                changed=build('body',snapshot,'body')
                assert changed['buildActions']==1 and changed['compiles']==1
                base=output/(kind+'-raw');workspace=fixture(base,kind,args.packages,args.checkout)
                ordinary=raw(base,workspace,kind,args.packages,label='unchanged')
                assert ordinary['managedHashes']==recovered['managedHashes']
                mutate(workspace,kind,'body');edited=raw(base,workspace,kind,args.packages,label='body')
                assert edited['managedHashes']==changed['managedHashes']
                if kind=='serilog':
                    assert recovered['testActions']==1 and recovered['test']['passed']
                    def puts():
                        with urllib.request.urlopen(args.endpoint+'/metrics',timeout=10) as response: text=response.read().decode()
                        return sum(float(line.rsplit(' ',1)[1]) for line in text.splitlines() if line.startswith('http_request_duration_seconds_count{') and 'method="PUT"' in line)
                    before=puts()
                    failed=build('failed-test',snapshot,'failed-test',upload=True)
                    assert failed['actionCache']['stagedObjects']>0 and puts()==before
                    assert failed['actionCache']['publishedObjects']==0 and failed['remote']['transport']['putRequests']==0
                report.setdefault('parity',[]).append(dict(kind=kind,unchanged=True,body=True))
        report['accepted']=True
    finally:save()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('role',choices=['produce','consume'])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--packages',type=Path,required=True)
    p.add_argument('--checkout',type=Path)
    p.add_argument('--endpoint',required=True)
    p.add_argument('--handoff',type=Path)
    p.add_argument('--workloads',nargs='+',choices=['diamond','serilog'],default=['diamond','serilog'])
    run(p.parse_args())
