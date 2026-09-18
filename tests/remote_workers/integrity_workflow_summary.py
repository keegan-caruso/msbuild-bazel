"""Aggregate paired integrity diagnostics; leaf operation times are nested in scans."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def group(item):
    if item['category']!='scan':return item['category']
    p=item['path']
    if p.startswith('/nix/store/'):return 'runtimeScan'
    if '/tools/' in p or p.endswith('/bazel'):return 'controllerScan'
    if p.endswith('/workspace'):return 'workspaceAndPackagesScan'
    if p.endswith('/plan'):return 'planScan'
    return 'otherScan'


def summarize(path):
    d=json.loads(path.read_text());assert d['accepted']
    out=dict(accepted=True,revision=d['revision'],sourceReportSha256=hashlib.sha256(path.read_bytes()).hexdigest(),groups=[],rootCosts=[],diagnostics=[])
    for s in d['samples']:
        if not s['profile']:continue
        r=s['result'];by={};roots=[]
        for phase in ['identity','leaseExit']:
            items=[i for i in r['integrityProfile'] if i['phase']==phase]
            totals={}
            for i in items:totals[group(i)]=totals.get(group(i),0)+i['seconds']
            totals['unattributed']=r['phases'][phase]-sum(i['seconds'] for i in items)
            scans=[i for i in items if i['category']=='scan']
            by[phase]=dict(total=r['phases'][phase],components=totals,files=sum(i['files'] for i in scans),logicalBytes=sum(i['contentBytes'] for i in scans),hashedBytes=sum(i['contentBytes']-i['reusedBytes'] for i in scans),reusedBytes=sum(i['reusedBytes'] for i in scans),scanOperations={k:sum(i['phases'].get(k,{}).get('seconds',0) for i in scans) for k in ['open','read','hash','fileManifest']})
        out['diagnostics'].append(dict(kind=s['kind'],case=s['case'],repetition=s['repetition'],phases=by,leaseVerification=r['leaseVerification'],roots=r['integrityProfile']))
    for kind in ['diamond','serilog']:
        timed=[s for s in d['samples'] if s['kind']==kind and s['case']=='reused-hit']
        diag=[s for s in out['diagnostics'] if s['kind']==kind and s['case']=='reused-hit']
        row=dict(kind=kind,samplesPerMode=3)
        for mode in [False,True]:
            selected=[s['result'] for s in timed if s['profile']==mode]
            row['profiled' if mode else 'unprofiled']={k:statistics.median(s['phases'][k] for s in selected) for k in ['identity','leaseExit']}
        row['components']={p:{k:statistics.median(s['phases'][p]['components'].get(k,0) for s in diag) for k in sorted(set().union(*(s['phases'][p]['components'] for s in diag)))} for p in ['identity','leaseExit']}
        row['scanOperations']={p:{k:statistics.median(s['phases'][p]['scanOperations'][k] for s in diag) for k in ['open','read','hash','fileManifest']} for p in ['identity','leaseExit']}
        out['groups'].append(row)
        for phase in ['identity','leaseExit']:
            paths=sorted({i['path'] for s in diag for i in s['roots'] if i['phase']==phase and i['category']=='scan'})
            for root in paths:
                vals=[i for s in diag for i in s['roots'] if i['phase']==phase and i['category']=='scan' and i['path']==root]
                out['rootCosts'].append(dict(kind=kind,phase=phase,path=root,seconds=statistics.median(i['seconds'] for i in vals),hashedBytes=vals[0]['contentBytes']-vals[0]['reusedBytes'],files=vals[0]['files']))
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('report',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.write_text(json.dumps(summarize(a.report),indent=2)+'\n')
