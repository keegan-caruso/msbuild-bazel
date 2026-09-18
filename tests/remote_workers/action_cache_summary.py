"""Compact accepted action-cache reports without losing misses or rejection cases."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(path):
    report=json.loads(path.read_text())
    if not report['accepted']:raise ValueError('Incomplete qualification')
    cases=[]
    for case in report['cases']:
        value=case['result']
        cases.append(dict(kind=case['kind'],case=case['case'],accepted=value['accepted'],seconds=value['wallSeconds'],
            buildActions=value.get('buildActions'),remoteBuildHits=value.get('remoteBuildHits'),compiles=value.get('compiles'),
            testActions=value.get('testActions'),testPassed=value.get('test',{}).get('passed'),phases=value['phases'],
            actionCache=value.get('actionCache'),innerPutRequests=value.get('remote',{}).get('transport',{}).get('putRequests'),
            managedHashesDigest=hashlib.sha256(json.dumps(value.get('managedHashes',{}),sort_keys=True).encode()).hexdigest()))
    return dict(source=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),revision=report['revision'],
        scope=report['scope'],accepted=True,service=report['service'],harnessSha256=report['harnessSha256'],
        cases=cases,comparisons=report['comparisons'],medians=report['medians'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reports',type=Path,nargs='+');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.write_text(json.dumps([summarize(path) for path in a.reports],indent=2)+'\n')
