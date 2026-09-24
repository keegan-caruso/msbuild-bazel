"""Small Immutable expansion: existing net9 contract/implementation plus a net10 consumer.

The upstream net10 test graph reaches source-built framework projects and is a
later gate. This script deliberately does not qualify or retarget those tests.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

control,folder=map(lambda p:Path(p).resolve(),sys.argv[1:]);folder.mkdir(parents=True,exist_ok=False)
rules=Path(__file__).resolve().parents[3];source=control/'source';sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];records=[]
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()=='60629d14374c56f1cb51819049ad1fa529307f8d'
def run(name,cmd,cwd=folder,allowed=(0,)):
    with (folder/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,cmd)),cwd=cwd,stdout=log,stderr=subprocess.STDOUT,timeout=900,env=dict(os.environ,DOTNET_ROOT=str(sdk)))
    records.append(dict(case=name,exitCode=r.returncode));print(name,r.returncode,flush=True);assert r.returncode in allowed,(name,r.returncode)
run('sparse',['git','sparse-checkout','add','src/libraries/System.Collections.Immutable','src/libraries/System.Collections/ref','src/libraries/System.Runtime/ref'],source)
entry='src/libraries/System.Collections.Immutable/src/System.Collections.Immutable.csproj'
props=dict(json.loads((control/'report.json').read_text())['properties'],TargetFramework='net9.0',RestoreUseStaticGraphEvaluation='false',NetCoreSdkRoot=str(sdk/'sdk/10.0.400'))
run('raw-build',[sdk/'dotnet','build',entry,*['-p:'+k+'='+v for k,v in props.items()],'-bl:'+str(folder/'raw.binlog')],source)
probe=folder/'inventory';probe.mkdir()
for original,dest in [('Inventory.cs.txt','Program.cs'),('Inventory.csproj.txt','Inventory.csproj')]:shutil.copyfile(Path(__file__).with_name(original),probe/dest)
(probe/'selection.json').write_text(json.dumps(dict(entries=[entry],framework='net9.0')))
run('inventory-build',[sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'])
run('inventory',[sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,probe/'selection.json',probe/'inventory.json'])
w=folder/'bazel';run('declarations',[sys.executable,Path(__file__).with_name('prepare.py'),source,probe/'inventory.json',w,rules])
name='src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net9.0'
build=w/'upstream/BUILD.bazel';build.write_text(build.read_text().replace('name="'+name+'_paired",','name="'+name+'_paired",visibility=["//visibility:public"],'))
smoke=w/'smoke';smoke.mkdir()
(smoke/'Smoke.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../upstream/'+entry+'" SetTargetFramework="TargetFramework=net9.0" /></ItemGroup></Project>')
(smoke/'Program.cs').write_text('''using System;
using System.Collections.Immutable;
using System.Collections.Frozen;
using System.IO;
using System.Security.Cryptography;
var array = ImmutableArray.Create(1, 2, 3).Add(4);
if (array.Length != 4 || array[3] != 4) return 1;
var dict = ImmutableDictionary<string,int>.Empty.Add("answer", 42);
if (dict["answer"] != 42) return 2;
if (!new[] { "a", "b" }.ToFrozenSet().Contains("b")) return 3;
Console.WriteLine(Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ImmutableArray).Assembly.Location))));
return 0;
''')
(smoke/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_test")\nmsbuild_test(name="smoke",project="Smoke.csproj",assembly_name="Smoke",target_framework="net10.0",test_protocol="executable",test_output_type="exe",srcs=["Program.cs"],deps=["//upstream:'+name+'_paired"],linux_worker=True,size="small")\n')
start=[bazel,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files'];flags=['--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1']
try:
    run('bazel-smoke',start+['test','//smoke','--test_output=errors']+flags,w)
    impl=w/'bazel-bin/upstream'/(name+'.runtime/System.Collections.Immutable.dll')
    digest=hashlib.sha256(impl.read_bytes()).hexdigest()
    assert digest.upper() in (w/'bazel-testlogs/smoke/smoke/test.log').read_text(),'Consumer did not load the Bazel implementation'
    reference=w/'bazel-bin/upstream/src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net9.0.reference/System.Collections.Immutable.dll'
    raw=source/'artifacts/bin/System.Collections.Immutable'
    pack=next(k for k in json.loads((w/'package-lock.json').read_text()) if k.lower().startswith('microsoft.netcore.app.ref/9.'))
    refs=w/'bazel-bin/upstream'/('archive_'+pack.replace('/','_').lower()+'.package/ref/net9.0')
    assert refs.is_dir(),refs
    api=os.environ['RULES_MSBUILD_APICOMPAT']
    def compare(case,left,right,strict=False,allowed=(0,)):
        run(case,[api,'-l',left,'-r',right,'--lref',refs,'--rref',refs,'--enable-rule-attributes-must-match','--enable-rule-cannot-change-parameter-name']+(['--strict-mode'] if strict else []),allowed=allowed)
    compare('raw-contract-implementation',raw/'ref/Release/net9.0/System.Collections.Immutable.dll',raw/'Release/net9.0/System.Collections.Immutable.dll',allowed=(1,))
    compare('contract-implementation',reference,impl,allowed=(1,))
    def diagnostics(case):return sorted(line for line in (folder/(case+'.log')).read_text().splitlines() if line.startswith('CP'))
    inherited=diagnostics('raw-contract-implementation')
    assert len(inherited)==16 and inherited==diagnostics('contract-implementation'), 'Bazel added contract/implementation differences'
    compare('raw-bazel-contract',raw/'ref/Release/net9.0/System.Collections.Immutable.dll',reference,True)
    compare('raw-bazel-implementation',raw/'Release/net9.0/System.Collections.Immutable.dll',impl,True)
    run('noop',start+['test','//smoke','--execution_log_json_file='+str(folder/'noop.execution.json')]+flags,w)
    assert not (folder/'noop.execution.json').read_text().strip()
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=source,text=True).strip()
    (folder/'report.json').write_text(json.dumps(dict(bazel=subprocess.check_output([bazel,'--version'],text=True).strip(),platform='linux-arm64',sdk='10.0.400',framework='net9.0',consumerFramework='net10.0',sourceUnchanged=True,linkerTrimmingEnabled=True,smokeLoadedBazelImplementationSha256=digest,upstreamTestsQualified=False,inheritedContractAttributeDifferences=inherited,commands=records),indent=2)+'\n')
finally:subprocess.run(start+['shutdown'],cwd=w,check=True)
