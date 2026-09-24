"""Summarize BEP phases and overlapping trace intervals from profile_recovery.py."""
import argparse
import gzip
import json
from pathlib import Path
import statistics

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('folder', type=Path)
a = p.parse_args()
rows = json.loads((a.folder / 'samples.json').read_text())

def union_seconds(events):
    intervals = sorted((e['ts'], e['ts'] + e['dur']) for e in events if 'dur' in e)
    total = 0
    end = float('-inf')
    for start, stop in intervals:
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total / 1e6

for row in rows:
    folder = a.folder / (row['mode'] + '-' + str(row['repeat']))
    events = [json.loads(line) for line in (folder / 'events.json').read_text().splitlines()]
    metrics = next(e['buildMetrics'] for e in events if 'buildMetrics' in e)
    timing = metrics['timingMetrics']
    row['commandSeconds'] = int(timing['wallTimeInMs']) / 1000
    row['outsideCommandSeconds'] = max(0, row['seconds'] - row['commandSeconds'])
    row['analysisSeconds'] = int(timing['analysisPhaseTimeInMs']) / 1000
    row['executionSeconds'] = int(timing['executionPhaseTimeInMs']) / 1000
    row['otherCommandSeconds'] = max(0, row['commandSeconds'] - row['analysisSeconds'] - row['executionSeconds'])
    trace = json.load(gzip.open(folder / 'profile.json.gz', 'rt'))['traceEvents']
    for key, category in [('cacheLookupUnionSeconds', 'remote action cache check'),
                          ('downloadUnionSeconds', 'remote output download')]:
        row[key] = union_seconds(e for e in trace if e.get('cat') == category)
    row['merkleUnionSeconds'] = union_seconds(e for e in trace if e.get('name') == 'MerkleTreeComputer.buildForSpawn')
    row['sourceBytesRead'] = int(metrics['artifactMetrics']['sourceArtifactsRead']['sizeInBytes'])

medians = {}
for mode in sorted({r['mode'] for r in rows}):
    selected = [r for r in rows if r['mode'] == mode]
    medians[mode] = {k: round(statistics.median(r[k] for r in selected), 3)
                     for k in selected[0] if k not in ['mode', 'repeat']}
result = dict(samples=rows, medians=medians,
              notes=['Fresh server/output base; repository cache and worker CAS may be warm.',
                     'Network counters include non-loopback client traffic, not only CAS payloads.',
                     'Trace union durations overlap each other and phases; do not add them.',
                     'Outside-command time includes client/server startup and finalization.'])
(a.folder / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(medians, indent=2))
