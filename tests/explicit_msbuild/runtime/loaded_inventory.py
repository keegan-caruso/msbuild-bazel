"""Rank installed runtime files observed by the qualification hook (including its own dependencies)."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('parity',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('--require-empty',action='store_true')
a=parser.parse_args()
data=json.loads(a.parity.read_text())
installed=set(data['installedComponents'])
counts=Counter();suites=defaultdict(set);entries=defaultdict(Counter)
for test in data['tests']:
    for proof in test['proofs']:
        for name,row in proof['files'].items():
            # A private source-built formatter and the installed shared formatter
            # legitimately have the same filename. Classify the observed path.
            if name not in installed or row['expectedPath'].startswith('private/'):continue
            counts[name]+=1;suites[name].add(test['assembly']);entries[name][proof['entry']]+=1
rows=[dict(file=n,processes=c,suites=sorted(suites[n]),processEntries=dict(entries[n])) for n,c in sorted(counts.items(),key=lambda x:(-x[1],x[0]))]
a.output.write_text(json.dumps(dict(note='Observed loads include startup-hook and test-runner dependencies, not just test bodies.',components=rows),indent=2)+'\n')
print(len(rows),'installed components observed')
if a.require_empty:assert not rows, [r['file'] for r in rows]
