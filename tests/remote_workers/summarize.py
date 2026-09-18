"""Validate completed sample groups and retain compact reproducible timing evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def summarize(inputs,output):
    runs=[];samples=[];revision=None
    for path in inputs:
        value=json.loads(path.read_text())
        if revision is None:revision=value['revision']
        if value['revision']!=revision:raise ValueError('production candidates differ')
        runs.append(dict(path=path.parent.name+"/"+path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         wholeRunAccepted=value['accepted'],harnessSha256=value['harnessSha256']))
        samples+=value['samples']
    report=dict(schemaVersion=1,candidate=revision,correctnessAccepted=False,independentWorkerAcceptance=False,
                scope='same-host macOS ARM64, real loopback bazel-remote; fresh adapter consumers versus retained raw MSBuild except empty-cache case',
                inputReports=runs,samples=[],medians=[])
    for kind in ('diamond','serilog'):
        for case in ('unchanged','body','api','empty'):
            selected=sorted((s for s in samples if s['kind']==kind and s['case']==case),key=lambda s:s['repetition'])
            if [s['repetition'] for s in selected]!=[0,1,2]:raise ValueError('Need exactly three complete repetitions: '+kind+' '+case)
            for sample in selected:
                n=sample['native'];r=sample['raw']
                assert n['accepted'] and n['workerCacheEligible'] and n['managedHashes']==r['managedHashes']
                expected=0 if case=='unchanged' else 1 if case=='body' else 4 if kind=='diamond' else 2
                assert n['compiles']==expected
                if kind=='serilog':assert n['test']['passed'] and r['test']['passed']==1
                else:assert n['applicationOutput']==r['applicationOutput']
                report['samples'].append(dict(kind=kind,case=case,repetition=sample['repetition'],rawSeconds=r['seconds'],nativeSeconds=n['wallSeconds'],
                    rawCompiles=r['compiles'],nativeCompiles=n['compiles'],managedBytesEqual=True,phases=n['phases'],transport=n['remote']['transport']))
            raw=statistics.median(s['raw']['seconds'] for s in selected);native=statistics.median(s['native']['wallSeconds'] for s in selected)
            transport={k:statistics.median(s['native']['remote']['transport'][k] for s in selected) for k in selected[0]['native']['remote']['transport']}
            phases={k:statistics.median(s['native']['phases'].get(k,0) for s in selected) for k in set().union(*(s['native']['phases'] for s in selected))}
            report['medians'].append(dict(kind=kind,case=case,rawSeconds=raw,nativeSeconds=native,ratio=native/raw,nativeCompiles=selected[0]['native']['compiles'],
                phases=phases,transport=transport,withinDiagnosticTarget=native<=raw*1.25+.25 if case!='empty' else None))
    report['correctnessAccepted']=True
    report['performanceTargetMet']=all(v['withinDiagnosticTarget'] for v in report['medians'] if v['withinDiagnosticTarget'] is not None)
    output.write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('reports',nargs='+',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();summarize(args.reports,args.output)
