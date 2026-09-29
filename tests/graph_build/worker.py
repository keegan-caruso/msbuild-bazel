"""Run one fixed-path graph action on an independently prepared worker."""

import json
import os
from pathlib import Path
import sys

from qualify import DOTNET, RUNNER, fixture, run

root = Path(sys.argv[1]).resolve()
variant = sys.argv[2]
root.mkdir(parents=True, exist_ok=False)
contract = fixture(root)
contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
for i in range(3):
    declaration = contract['Projects'][f'P{i}/P{i}.csproj']
    declaration['ReferenceBoundary'] = True
    declaration['DependencyCopies'] = {
        f'P{i}/bin/Release/net10.0/P{dependency}.{extension}':
        f'P{dependency}/bin/Release/net10.0/P{dependency}.{extension}'
        for dependency in range(i) for extension in ('dll', 'pdb')
    }
if variant == 'body':
    (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
manifest = root.parent / 'contract.json'
manifest.write_text(json.dumps(contract))
report = root.parent / 'report.json'
run(DOTNET, RUNNER, 'build', root, manifest, report, root.parent / 'snapshots')
result = json.loads(report.read_text())
assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == ('2' if variant == 'body' else '1')
print(json.dumps(result))
