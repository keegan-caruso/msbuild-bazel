"""Compare asset strings in reference DLLs preserved by an Orchard disk-cache run.

Run after the benchmark, outside timed samples. Inputs are its state directory,
a baseline execution log, an API-edit execution log, and an output JSON path.
"""
import argparse
import gzip
import json
from pathlib import Path
import re

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('state', type=Path)
p.add_argument('before', type=Path)
p.add_argument('after', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()

def references(path):
    with gzip.open(path, 'rt') if path.suffix == '.gz' else path.open() as stream:
        text = stream.read()
    decoder = json.JSONDecoder()
    offset = 0
    result = {}
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        action, offset = decoder.raw_decode(text, offset)
        for entry in action.get('actualOutputs', []):
            if '.reference/' in entry['path'] and entry['path'].endswith('.dll'):
                result[Path(entry['path']).name] = entry['digest']['hash']
    return result

def asset_strings(digest):
    content = (a.state / 'cache/cas' / digest[:2] / digest).read_bytes()
    return [value.decode() for value in re.findall(rb'[\x20-\x7e]{20,}', content) if b'|/__rules_msbuild/in/' in value]

def normalize(values):
    return [re.sub('/__rules_msbuild/in/[0-9a-f]{64}/', '/__rules_msbuild/in/CONTENT/', value) for value in values]

before = references(a.before)
after = references(a.after)
rows = []
for name, digest in sorted(after.items()):
    if name not in before or before[name] == digest:
        continue
    old, new = asset_strings(before[name]), asset_strings(digest)
    if not old or not new:
        continue
    row = dict(assembly=name, assetStrings=len(old), stringsDiffer=old != new,
               sameAfterRemovingContentIdentity=normalize(old) == normalize(new))
    if name == 'OrchardCore.Setup.dll':
        row.update(exampleBefore=old[0], exampleAfter=new[0])
    rows.append(row)
a.output.write_text(json.dumps(rows, indent=2) + '\n')
print('Changed references with asset paths:', len(rows))
print('Matching asset strings after removing content identity:', sum(r['sameAfterRemovingContentIdentity'] for r in rows))
