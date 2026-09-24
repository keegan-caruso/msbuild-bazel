"""Verify the composed source-only host and reject an explicitly supplied SDK fallback."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

w,out=[Path(p).resolve() for p in sys.argv[1:]]
out.mkdir(parents=True,exist_ok=False)
m=json.loads((w/'subset.json').read_text());assert m['sourceOnly'] and not m['installed']
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
host=w/'bazel-bin/runtime/tree.layout'
assert (host/'host.sh').is_file(), 'Build the host layout first'
assert sorted(p.name for p in (host/'shared/Microsoft.NETCore.App').iterdir())==[m['frameworkVersion']]
expected={}
for name,label in m['managed'].items():
    package,target=label.removeprefix('//').split(':')
    expected['shared/Microsoft.NETCore.App/'+m['frameworkVersion']+'/'+name]=w/'bazel-bin'/package/(target+'.runtime')/name
for name,label in m.get('private',{}).items():
    package,target=label.removeprefix('//').split(':')
    expected['private/'+name]=w/'bazel-bin'/package/(target+'.runtime')/name
for name,label in m['native'].items():
    package,_=label.removeprefix('//').split(':')
    expected[m['nativePaths'][name]]=w/'bazel-bin'/package/'runtime.generated'/name
expected['probe/Probe.dll']=w/'bazel-bin/load_probe/probe.runtime/Probe.dll'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
actual={str(p.relative_to(host)):sha(p) for p in host.rglob('*') if p.is_file() and (p.suffix in ['.dll','.so'] or p.name=='dotnet')}
assert actual=={path:sha(p) for path,p in expected.items()},(sorted(set(actual)-set(expected)),sorted(set(expected)-set(actual)))
project=out/'Guard.csproj'
project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
(out/'Program.cs').write_text('using System; using System.Reflection; if (args.Length != 0) Assembly.LoadFile(args[0]); Console.WriteLine(typeof(object).Assembly.GetName().Version);')
with (out/'build.log').open('w') as log:subprocess.run([sdk/'dotnet','build',project,'-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
name='System.Text.Encoding.CodePages.dll';assert name in m['excludedRuntimeComponents']
fallback=sdk/'shared/Microsoft.NETCore.App/10.0.11'/name;assert fallback.is_file()
records=[]
for case,args,success in [('source-host',[],True),('excluded-sdk-fallback',[fallback],False)]:
    command=[host/'host.sh',out/'bin/Release/net10.0/Guard.dll',*args]
    p=subprocess.run(list(map(str,command)),env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(out/(case+'-proof'))),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=60)
    (out/(case+'.log')).write_text(p.stdout)
    assert (p.returncode==0)==success,(case,p.returncode,p.stdout)
    if not success:assert 'Qualification loaded wrong binary' in p.stdout and name in p.stdout,p.stdout
    records.append(dict(case=case,exitCode=p.returncode,expectedSuccess=success))
(out/'report.json').write_text(json.dumps(dict(frameworkVersion=m['frameworkVersion'],binaryHashes=actual,excludedRuntimeComponents=m['excludedRuntimeComponents'],controls=records),indent=2)+'\n')
print('Exact source-only binary manifest and excluded-fallback negative control passed',flush=True)
