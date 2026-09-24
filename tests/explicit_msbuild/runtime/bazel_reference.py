"""Build the pinned reference/tool slice; compare metadata and execute a consumer."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

rules = Path(__file__).resolve().parents[3]
control, folder = (Path(p).resolve() for p in sys.argv[1:])
folder.mkdir(parents=True, exist_ok=False)
source = control/'source'
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
bazel = os.environ['RULES_MSBUILD_BAZEL']
commit = '60629d14374c56f1cb51819049ad1fa529307f8d'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip() == commit
assert json.loads((control/'report.json').read_text())['sourceUnchanged']
records=[]
def run(case, command, cwd=folder):
    with (folder/(case+'.log')).open('w') as log:
        result=subprocess.run([str(x) for x in command],cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    records.append({'case':case,'exitCode':result.returncode})
    print(case,result.returncode,flush=True)
    result.check_returncode()
probe=folder/'inventory';probe.mkdir()
for original,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:
    shutil.copyfile(Path(__file__).with_name(original),probe/dest)
entry='src/libraries/Microsoft.Extensions.Primitives/ref/Microsoft.Extensions.Primitives.csproj'
(probe/'selection.json').write_text(json.dumps({'entries':[entry]}))
run('inventory-build',[sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'])
run('inventory',[sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,probe/'selection.json',probe/'inventory.json'])
workspace=folder/'bazel'
run('declarations',[sys.executable,Path(__file__).with_name('prepare.py'),source,probe/'inventory.json',workspace,rules])
target='//upstream:src_libraries_Microsoft.Extensions.Primitives_ref_Microsoft.Extensions.Primitives_net10.0'
startup=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1']
try:
    run('build',startup+['build',target,'--execution_log_json_file='+str(folder/'build.execution.json')]+flags,workspace)
    run('noop',startup+['build',target,'--execution_log_json_file='+str(folder/'noop.execution.json')]+flags,workspace)
    assert not (folder/'noop.execution.json').read_text().strip(), 'No-op must execute no actions'
    name=target.split(':')[1]
    reference=workspace/'bazel-bin/upstream'/f'{name}.reference/Microsoft.Extensions.Primitives.dll'
    raw=source/'artifacts/bin/Microsoft.Extensions.Primitives/ref/Release/net10.0/Microsoft.Extensions.Primitives.dll'
    inspect=folder/'inspect';inspect.mkdir()
    shutil.copyfile(rules/'tests/explicit_msbuild/aspnetcore/Inspect.cs.txt',inspect/'Program.cs')
    (inspect/'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
    run('inspect-build',[sdk/'dotnet','build',inspect/'Inspect.csproj','-c','Release'])
    def metadata(path):
        return json.loads(subprocess.check_output([sdk/'dotnet',inspect/'bin/Release/net10.0/Inspect.dll',path],text=True))
    a,b=metadata(raw),metadata(reference)
    removed=[]
    # /refonly drops non-public constructors from upstream's authored contract.
    # Allow only this difference; every other inspected type/method/field/resource
    # record must match. This is not a complete API-compatibility implementation.
    for left,right in zip(a['types'],b['types']):
        missing=[m for m in left['methods'] if m not in right['methods']]
        assert all(m['name']=='.ctor' and m['attributes'] & 7 in (1,3) for m in missing),missing
        removed.extend({'type':left['name'],'method':m} for m in missing)
        left['methods']=[m for m in left['methods'] if m not in missing]
    assert a == b, 'Reference type/method/field/resource metadata differs'
    smoke=folder/'smoke';smoke.mkdir()
    for path in ['Smoke.csproj','Program.cs']:shutil.copyfile(control/'smoke'/path,smoke/path)
    run('consumer-compile',[sdk/'dotnet','build',smoke/'Smoke.csproj','-c','Release','-p:Contract='+str(reference),'-p:NuGetAudit=false'])
    implementation=source/'artifacts/bin/Microsoft.Extensions.Primitives/Release/net10.0/Microsoft.Extensions.Primitives.dll'
    shutil.copyfile(implementation,smoke/'bin/Release/net10.0/Microsoft.Extensions.Primitives.dll')
    run('consumer-execute',[sdk/'dotnet',smoke/'bin/Release/net10.0/Smoke.dll',hashlib.sha256(implementation.read_bytes()).hexdigest()])
    execution=(folder/'build.execution.json').read_text();actions=[];decoder=json.JSONDecoder()
    while execution.strip():
        action,end=decoder.raw_decode(execution.lstrip());execution=execution.lstrip()[end:]
        if action.get('mnemonic')=='MSBuildAssembly':actions.append({'target':action['targetLabel'],'cacheHit':action.get('cacheHit',False)})
    assert len(actions)==7 and not any(a['cacheHit'] for a in actions),actions
    assert len(set(a['target'] for a in actions))==6,actions
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    report={'commit':commit,'bazel':subprocess.check_output([bazel,'--version'],text=True).strip(),'sdk':'10.0.400','platform':'linux-arm64','sourceUnchanged':True,'commands':records,'assemblyActions':actions,'lockedPackages':len(json.loads((workspace/'package-lock.json').read_text())),'referenceBytesEqual':raw.read_bytes()==reference.read_bytes(),'inspectedMetadataEqualExceptNonPublicConstructors':True,'omittedConstructors':removed,'rawReferenceSha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'bazelReferenceSha256':hashlib.sha256(reference.read_bytes()).hexdigest(),'consumerUsesRawImplementation':True,'upstreamTestsQualified':False,'remoteCacheQualified':False}
    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
