"""Summarize SDK evaluation profiles without mixing nested pass durations."""
import collections
import json
from pathlib import Path
import statistics
import sys

root=Path(sys.argv[1]); results=json.loads((root/'results.json').read_text())
profiled=[r for r in results if r.get('instrumented')]
passes=collections.Counter(); files=collections.Counter(); hotspots=collections.Counter(); phases=collections.Counter(); records=0
for run in profiled:
    rows=json.loads((root/run['case']/'compilation.json').read_text())
    assert len(rows)==129
    for row in rows:
        assert len(row['evaluations'])==1, row['project']
        records+=1
        for key,value in row['phases'].items(): phases[key]+=value['wallSeconds']/len(profiled)
        evaluation=row['evaluations'][0]
        for p in evaluation['passes']:passes[p['pass']]+=p['inclusiveSeconds']/len(profiled)
        for f in evaluation['files']:
            key=f['file'].split('/sdk/10.0.400/')[-1] if '/sdk/10.0.400/' in f['file'] else '<project/generated>'
            files[key]+=f['exclusiveSeconds']/len(profiled)
        for h in evaluation['hotspots']:
            key=(Path(h['file']).name+':'+str(h['line'])+' '+str(h['elementName'])+' '+h['kind'])
            hotspots[key]+=h['exclusiveSeconds']/len(profiled)
summary=dict(runs=results,evaluationRecords=records,
             uninstrumentedMeanSeconds=statistics.mean(r['buildSeconds'] for r in results if r['case'].startswith('control')),
             instrumentedMeanSeconds=statistics.mean(r['buildSeconds'] for r in profiled),
             meanSummedPhaseSeconds=dict(phases),meanSummedPassInclusiveSeconds=dict(passes),
             meanSummedFileExclusiveSeconds=dict(files.most_common()),
             sampledHotspotExclusiveSeconds=dict(hotspots.most_common(25)))
(root/'evaluation-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
for key in ('uninstrumentedMeanSeconds','instrumentedMeanSeconds','meanSummedPhaseSeconds','meanSummedPassInclusiveSeconds'): print(key,summary[key])
print('Top files',files.most_common(10)); print('Top hotspots',hotspots.most_common(10))
