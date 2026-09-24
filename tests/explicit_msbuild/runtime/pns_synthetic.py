"""Prove the explicit contract-source edge runs upstream unsupported-API generation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

workspace,raw_host,out=[Path(p).resolve() for p in sys.argv[1:]]
out.mkdir(parents=True,exist_ok=False)
(out/'PnsSmoke.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><NoWarn>CA1416</NoWarn></PropertyGroup></Project>')
(out/'Program.cs').write_text('''using System;
using System.Linq;
using System.Reflection;
using System.Security.Principal;
if (!typeof(WindowsIdentity).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Any(a => a.Key == "NotSupported" && a.Value == "True")) return 2;
try { using var identity = WindowsIdentity.GetCurrent(); return 1; }
catch (PlatformNotSupportedException) { Console.WriteLine("Generated unsupported-platform API verified"); return 0; }
''')
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
with (out/'build.log').open('w') as log:subprocess.run([sdk/'dotnet','build',out/'PnsSmoke.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
manifest=json.loads((workspace/'subset.json').read_text())
name='System.Security.Principal.Windows.dll'
package,target=manifest['managed'][name].removeprefix('//').split(':')
producer=workspace/'bazel-bin'/package/(target+'.runtime')/name
records=[]
for kind,host in [('raw',raw_host),('bazel',workspace/'bazel-bin/runtime/tree.layout')]:
    proof=out/(kind+'-proof')
    with (out/(kind+'.log')).open('w') as log:
        p=subprocess.run([host/'host.sh',out/'bin/Release/net10.0/PnsSmoke.dll'],env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(proof)),stdout=log,stderr=subprocess.STDOUT,timeout=30)
    assert p.returncode==0,(kind,p.returncode)
    proofs=[json.loads(p.read_text()) for p in proof.glob('runtime-*.json')]
    assert len(proofs)==1 and proofs[0]['entry']=='PnsSmoke',proofs
    observed=proofs[0]['files'][name]
    expected=producer if kind=='bazel' else host/'shared/Microsoft.NETCore.App/10.0.11'/name
    assert observed['sha256']==hashlib.sha256(expected.read_bytes()).hexdigest().upper()
    records.append(dict(kind=kind,exitCode=p.returncode,assembly=observed))
(out/'report.json').write_text(json.dumps(records,indent=2)+'\n')
print(json.dumps(records),flush=True)
