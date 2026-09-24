"""Compare all selected assemblies/resources and available raw reference metadata.

Raw assemblies are captured as <label>/implementation.dll and reference.dll.
Reference differences are accepted only for generated file-local type-name hashes;
this is a metadata/resource parity check, not a substitute for upstream test suites.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

raw, base, report, selection = map(Path, sys.argv[1:])
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
probe = report.parent/'inspect'
probe.mkdir(exist_ok=True)
(probe/'Program.cs').write_text(Path(__file__).with_name('Inspect.cs.txt').read_text())
(probe/'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
subprocess.run([sdk/'dotnet','build',probe/'Inspect.csproj','-c','Release'],check=True,stdout=subprocess.DEVNULL)
program=probe/'bin/Release/net10.0/Inspect.dll'
out=base/'execroot/_main/bazel-out/aarch64-fastbuild/bin/upstream'
def inspect(path): return json.loads(subprocess.check_output([sdk/'dotnet',program,path],text=True))
def normalized(data):
    # Roslyn file-local names hash the generated source path, which differs from
    # raw checkout paths under the hermetic namespace. Preserve every other byte.
    return re.sub(r'(<[^<>]*_g>F)[0-9A-F]{64}__',r'\1<path-hash>__',json.dumps(data,sort_keys=True))
rows=[]
for label in sorted(selection.read_text().splitlines()):
    directory = raw/label.split(':',1)[1]
    request=json.loads((out/(directory.name+'.request.json')).read_text())
    implementation=out/(directory.name+'.runtime')/(request['assembly']+'.dll')
    assert implementation.exists(), directory.name
    a=inspect(directory/'implementation.dll'); b=inspect(implementation)
    assert a['resources']==b['resources'], (directory.name,'resource mismatch')
    result=dict(target=directory.name,resourcesEqual=True,implementationBytesEqual=(directory/'implementation.dll').read_bytes()==implementation.read_bytes())
    reference=directory/'reference.dll'
    if reference.exists():
        target=out/(directory.name+'.reference')/(request['assembly']+'.dll')
        result['referenceBytesEqual']=reference.read_bytes()==target.read_bytes()
        result['referenceMetadataEqual']=normalized(inspect(reference))==normalized(inspect(target))
        assert result['referenceMetadataEqual'], (directory.name,'reference metadata mismatch')
    rows.append(result)
report.write_text(json.dumps(rows,indent=2)+'\n')
print('Verified',len(rows),'assembly resources;',sum('referenceMetadataEqual' in row for row in rows),'reference metadata comparisons;',sum(row.get('referenceBytesEqual',False) for row in rows),'byte-identical references',flush=True)
