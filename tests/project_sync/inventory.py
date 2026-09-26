"""Inventory pinned upstream declarations and attempt sync without running targets.

Usage: inventory.py ASPNETCORE_CHECKOUT RUNTIME_CHECKOUT OUTPUT_JSON
Source inventories are static; only the generator result represents evaluation.
The checkouts must be disposable: successful synchronization writes its output.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from test_sync import DOTNET, DLL, SDK

specs = [
    ('aspnetcore', '7387de91234d3ef751fa50b3d1bfede4130213ff', [
        'src/ObjectPool/src/Microsoft.Extensions.ObjectPool.csproj',
        'src/ObjectPool/test/Microsoft.Extensions.ObjectPool.Tests.csproj',
        'src/Http/Http.Abstractions/src/Microsoft.AspNetCore.Http.Abstractions.csproj',
    ]),
    ('runtime', '60629d14374c56f1cb51819049ad1fa529307f8d', [
        'src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj',
        'src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj',
        'src/libraries/System.Collections.Immutable/src/System.Collections.Immutable.csproj',
    ]),
]
report = {'scope': 'Pinned source inspection and local generator evaluation; not build/test qualification', 'repositories': []}
for checkout, (name, commit, projects) in zip(sys.argv[1:3], specs):
    root = Path(checkout).resolve()
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assert actual == commit, (name, actual)
    rows = []
    for project in projects:
        path = root / project
        document = ET.parse(path).getroot()
        items = []
        for group in document.findall('ItemGroup'):
            for item in group:
                items.append(dict(type=item.tag, attributes=item.attrib,
                                  metadata={node.tag:node.text for node in item},
                                  condition=group.get('Condition', '')))
        result = subprocess.run([str(DOTNET/'dotnet'), str(DLL), str(root), str(SDK), project], text=True, capture_output=True)
        rows.append(dict(project=project, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         sdk=document.get('Sdk'), items=items, exitCode=result.returncode,
                         diagnostic=result.stderr.strip().replace(str(root), '<checkout>').replace(str(SDK), '<sdk>')))
    report['repositories'].append(dict(repository=name, commit=commit, projects=rows))
Path(sys.argv[3]).write_text(json.dumps(report, indent=2)+'\n')
