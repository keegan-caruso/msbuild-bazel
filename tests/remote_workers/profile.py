"""Summarize existing Bazel traces; no additional timed build instrumentation."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics


def summarize(path):
    data=json.loads(gzip.decompress(path.read_bytes()))
    events=data['traceEvents']
    complete=[e for e in events if e.get('ph')=='X' and 'dur' in e]
    def duration(name):return sum(e['dur'] for e in complete if e.get('name')==name)/1e6
    markers={e['name']:e['ts'] for e in events if e.get('cat')=='build phase marker' and e.get('ph')!='X'}
    downloads=[e for e in complete if e.get('name','').startswith('download file:')]
    # Union prevents concurrent HTTP spans from double counting wall time.
    end=None;download_wall=0
    for start,stop in sorted((e['ts'],e['ts']+e['dur']) for e in downloads):
        download_wall+=max(0,stop-max(start,end if end is not None else start));end=max(stop,end or stop)
    actions={e['name']:duration(e['name']) for e in complete if e.get('cat')=='action processing'}
    phases={}
    names=['Initialize command','Evaluate target patterns','Load, analyze dependencies and build artifacts','Complete build']
    for first,second in zip(names,names[1:]):
        if first in markers and second in markers:phases[first]=(markers[second]-markers[first])/1e6
    return dict(profileSha256=hashlib.sha256(path.read_bytes()).hexdigest(),bazelVersion=data['otherData']['bazel_version'],
        launchSeconds=duration('Launch Blaze'),extractSeconds=duration('Extracting Bazel binary'),
        moduleMappingSeconds=duration('compute main repo mapping'),downloadSpans=len(downloads),downloadUnionSeconds=download_wall/1e6,
        criticalPathSeconds=sum(e['dur'] for e in complete if e.get('cat')=='critical path component')/1e6,
        sandboxCreateSeconds=duration('sandbox.createFileSystem'),phases=phases,actions=actions)


def report(path):
    source=json.loads(path.read_text());samples=[]
    for sample in source['samples']:
        root=path.parent/sample['kind']/(sample['case']+'-'+str(sample['repetition']))/'n/state/b'
        profiles=list(root.glob('command-*.profile.gz'))
        if len(profiles)!=1:raise ValueError('Expected exactly one build profile in '+str(root))
        samples.append(dict(kind=sample['kind'],case=sample['case'],repetition=sample['repetition'],**summarize(profiles[0])))
    medians=[]
    for kind,case in sorted({(s['kind'],s['case']) for s in samples}):
        selected=[s for s in samples if (s['kind'],s['case'])==(kind,case)]
        keys=['launchSeconds','extractSeconds','moduleMappingSeconds','downloadSpans','downloadUnionSeconds','criticalPathSeconds','sandboxCreateSeconds']
        medians.append(dict(kind=kind,case=case,**{k:statistics.median(s[k] for s in selected) for k in keys}))
    return dict(source=path.parent.name+'/'+path.name,accepted=source['accepted'],samples=samples,medians=medians)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('reports',type=Path,nargs='+');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.write_text(json.dumps([report(p) for p in args.reports],indent=2)+'\n')
