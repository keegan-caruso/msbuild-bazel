"""Keep compact, checked timing evidence for sequential overhead changes."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def summarize(path):
    report=json.loads(path.read_text())
    if not report['accepted']:raise ValueError('Incomplete run: '+str(path))
    samples=[]
    for sample in report['samples']:
        native=sample['native'];raw=sample['raw']
        if not (native['accepted'] and native['workerCacheEligible'] and native['managedHashes']==raw['managedHashes']):
            raise ValueError('Artifact/acceptance mismatch')
        expected=0 if sample['case']=='unchanged' else 1
        if native['compiles']!=expected:raise ValueError('Unexpected compile work set')
        samples.append(dict(kind=sample['kind'],case=sample['case'],repetition=sample['repetition'],
            seconds=native['wallSeconds'],rawSeconds=raw['seconds'],compiles=native['compiles'],managedBytesEqual=True,
            phases=native['phases'],verification=native['leaseVerification'],transport=native['remote']['transport']))
    medians=[]
    for kind,case in sorted({(s['kind'],s['case']) for s in samples}):
        selected=[s for s in samples if (s['kind'],s['case'])==(kind,case)]
        if sorted(s['repetition'] for s in selected)!=[0,1,2]:raise ValueError('Expected three repetitions')
        fields=['seconds','rawSeconds'];result={k:statistics.median(s[k] for s in selected) for k in fields}
        result['phases']={k:statistics.median(s['phases'].get(k,0) for s in selected) for k in set().union(*(s['phases'] for s in selected))}
        medians.append(dict(kind=kind,case=case,**result))
    return dict(source=path.parent.name+'/'+path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),revision=report['revision'],
        harnessSha256=report['harnessSha256'],producers=[dict(kind=p['kind'],seconds=p['result']['wallSeconds'],compiles=p['result']['compiles'],phases=p['result']['phases']) for p in report.get('producers',[])],sharedBazelInstall=report.get('sharedBazelInstall',False),sharedBazelRepository=report.get('sharedBazelRepository',False),samples=samples,medians=medians)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('reports',type=Path,nargs='+');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(json.dumps([summarize(p) for p in args.reports],indent=2)+'\n')
