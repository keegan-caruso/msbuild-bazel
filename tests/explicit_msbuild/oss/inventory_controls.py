"""Check configured edge properties and deterministic node identities."""
import json
import os
from pathlib import Path
import subprocess
import sys

probe=Path(sys.argv[1]).resolve();folder=Path(sys.argv[2]).resolve();folder.mkdir(parents=True)
(folder/'Parent').mkdir();(folder/'Child').mkdir()
(folder/'Parent/Parent.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="../Child/Child.csproj" AdditionalProperties="Flavor=Child" GlobalPropertiesToRemove="Drop" SetConfiguration="Configuration=Debug" /></ItemGroup></Project>')
(folder/'Child/Child.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),'restore',folder/'Parent/Parent.csproj','-p:NuGetAudit=false'],check=True)
entries=[dict(project='Parent/Parent.csproj',properties={'Flavor':value,'Drop':'remove'}) for value in ['One','Two']]
rows=[]
for i,order in enumerate([entries,list(reversed(entries))]):
 config=folder/f'config{i}.json';config.write_text(json.dumps(dict(properties={},entries=order)))
 output=folder/f'inventory{i}.json'
 subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),probe,folder,config,output],check=True)
 result=json.loads(output.read_text());assert len(result)==3,result
 child=next(r for r in result if r['project']=='Child/Child.csproj')
 props={k.lower():v for k,v in child['globalProperties'].items()}
 assert props['flavor']=='Child' and props['configuration']=='Debug' and 'drop' not in props,props
 assert all(r['references'][0]['node']==child['id'] for r in result if r['project']=='Parent/Parent.csproj')
 rows.append({r['id'] for r in result})
assert rows[0]==rows[1],rows
print('Configured properties, removal, sharing, and entry-order stability passed')
