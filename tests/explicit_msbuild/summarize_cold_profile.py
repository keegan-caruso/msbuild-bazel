"""Aggregate sequential phase timings; retain inclusive tasks separately."""
import collections
import gzip
import json
from pathlib import Path
import re
import statistics
import sys

root=Path(sys.argv[1]); results=json.loads((root/'results.json').read_text())
phases=collections.defaultdict(list); cpu=collections.defaultdict(list); tasks=collections.defaultdict(float); targets=collections.defaultdict(float); worker=collections.defaultdict(list); groups=collections.defaultdict(list); traces=collections.defaultdict(list)
profiles=[r for r in results if r.get('instrumented')]
for result in profiles:
    records=json.loads((root/result['case']/'compilation.json').read_text())
    totals=collections.Counter(); processors=collections.Counter()
    for record in records:
        elapsed=sum(p['wallSeconds'] for p in record['phases'].values())
        groups['first' if record['requestNumber']==1 else 'subsequent'].append(elapsed)
        for name,value in record['phases'].items():totals[name]+=value['wallSeconds'];processors[name]+=value['cpuSeconds']
        for name,value in record['tasks'].items():tasks[name]+=value['seconds']/len(profiles)
        for name,value in record['targets'].items():targets[name]+=value['seconds']/len(profiles)
    for name,value in totals.items():phases[name].append(value)
    for name,value in processors.items():cpu[name].append(value)
    totals=collections.Counter()
    for record in json.loads((root/result['case']/'workers.json').read_text()):
        for name in ('identitySeconds','snapshotSeconds','preparationSeconds','childSeconds','publicationSeconds'):totals[name]+=record[name]
    for name,value in totals.items():worker[name].append(value)
    trace=json.load(gzip.open(root/(result['case']+'.profile.gz'),'rt'))
    totals=collections.Counter()
    for event in trace['traceEvents']:
        if event.get('ph')=='X':totals[event.get('cat','')]+=event.get('dur',0)/1e6
    for name,value in totals.items():traces[name].append(value)
raw_tasks=collections.defaultdict(list)
for file in sorted(root.glob('raw-profile-*.log')):
    text=file.read_text().split('Task Performance Summary:')[-1]
    for milliseconds,name,count in re.findall(r'^\s*(\d+)\s+ms\s+(.+?)\s+(\d+)\s+calls\s*$',text,re.M):raw_tasks[name].append(int(milliseconds)/1000)
summary={
    'runs':results,
    'meanSummedWorkerSeconds':{k:statistics.mean(v) for k,v in worker.items()},
    'meanSummedPhaseSeconds':{k:statistics.mean(v) for k,v in phases.items()},
    'meanSummedChildCpuSeconds':{k:statistics.mean(v) for k,v in cpu.items()},
    'meanSummedInclusiveTaskSeconds':dict(sorted(tasks.items(),key=lambda p:-p[1])),
    'meanSummedInclusiveTargetSeconds':dict(sorted(targets.items(),key=lambda p:-p[1])),
    'rawSummedTaskSeconds':{k:statistics.mean(v) for k,v in raw_tasks.items()},
    'meanSummedBazelTraceSeconds':{k:statistics.mean(v) for k,v in traces.items()},
    'requestGroups':{k:dict(count=len(v),meanSeconds=statistics.mean(v),medianSeconds=statistics.median(v)) for k,v in groups.items()},
}
(root/'summary.json').write_text(json.dumps(summary,indent=2))
for section in ('meanSummedWorkerSeconds','meanSummedPhaseSeconds','requestGroups'):print(section,summary[section])
print('Top tasks:',list(summary['meanSummedInclusiveTaskSeconds'].items())[:12])
