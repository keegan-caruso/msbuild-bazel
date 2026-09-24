"""Prove remote compilation, tests, input invalidation and cache-only recovery.

Requires a Linux ARM64 REAPI worker with bash, bubblewrap and SDK OS libraries.
The worker must not have an installed SDK. See docs/remote-execution.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--platform-image', required=True)
p.add_argument('--download-sdk', action='store_true', help='Acquire SDK and bootstrap runner through dotnet.sdk')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
folder = a.output.resolve(); folder.mkdir(parents=True, exist_ok=False)
w = folder/'workspace'; w.mkdir()
sdk = None if a.download_sdk else os.environ['RULES_MSBUILD_DOTNET_ROOT']
bazel = os.environ['RULES_MSBUILD_BAZEL']
versions = {
    'bazel': subprocess.check_output([bazel, '--version'], text=True).strip(),
    'sdk': '10.0.400' if a.download_sdk else subprocess.check_output([str(Path(sdk)/'dotnet'), '--version'], text=True).strip(),
}
assert versions['bazel'] in ['bazel 8.8.0', 'bazel 9.2.0'], versions
assert versions['sdk'] == '10.0.400', versions
def put(name, text):
    path = w/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
put('MODULE.bazel', f'''module(name="remote_qualification")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(sdk)},include_runtime_closure=False)
register_toolchains("//:registered")
''')
put('BUILD.bazel', '''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test","msbuild_items")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="Library",project="Library.csproj",srcs=["Value.cs"],target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
msbuild_items(name="resources",item_type="EmbeddedResource",srcs=["message.txt"],metadata={"LogicalName":"message"})
msbuild_test(name="Tests",project="Tests.csproj",srcs=["Program.cs"],target_framework="net10.0",deps=[":Library"],items=[":resources"],data=["expected.txt"],linux_worker=True,allow_remote_execution=True)
''')
if a.download_sdk:
    put('MODULE.bazel', f'''module(name="remote_qualification")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",global_json="//:global.json",platforms=["linux-arm64"])
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')
    put('global.json', '{"sdk":{"version":"10.0.400","rollForward":"disable"}}')
    build = (w/'BUILD.bazel').read_text().splitlines()
    put('BUILD.bazel', '\n'.join(line for line in build if not line.startswith(('load("@rules_msbuild//msbuild:toolchain.bzl"', 'msbuild_toolchain(', 'toolchain(')))+'\nexports_files(["global.json"])\n')
put('Library.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
put('Tests.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="Library.csproj" /></ItemGroup></Project>')
put('Value.cs','public static class Value { public static int Get() => 9; }')
put('Program.cs','using System.IO; using System.Reflection; using var s=Assembly.GetExecutingAssembly().GetManifestResourceStream("message"); using var r=new StreamReader(s!); return Value.Get().ToString()+":"+r.ReadToEnd()==File.ReadAllText("expected.txt") ? 0 : 1;')
put('message.txt','resource'); put('expected.txt','9:resource')
records=[]
bootstrap_mnemonics = ['MSBuildRunnerBootstrap', 'DotnetSdkRuntime'] if a.download_sdk else []
def run(case, *, remote=True, fresh=False, cached=False, success=True, unavailable=False):
    base=folder/('recovery-base' if fresh else 'base')
    cmd=[bazel,'--batch','--host_jvm_args=-Xmx1024m','--output_base='+str(base),'--ignore_all_rc_files','test','//:Tests','--jobs=2','--disk_cache=','--test_output=errors','--execution_log_json_file='+str(folder/(case+'.execution.json'))]
    if remote:
        cmd += ['--remote_instance_name=rules-msbuild-qualification/'+folder.name,'--remote_executor='+('grpc://127.0.0.1:1' if unavailable else a.executor),'--remote_cache='+('grpc://127.0.0.1:1' if unavailable else a.executor),'--remote_timeout=5s','--remote_retries=0','--noremote_local_fallback','--spawn_strategy=remote','--strategy=MSBuildAssembly=remote','--strategy=TestRunner=remote','--remote_download_outputs=all','--remote_accept_cached='+str(cached).lower(),'--remote_upload_local_results=false','--remote_default_exec_properties=ISA=aarch64','--remote_default_exec_properties=OSFamily=linux','--remote_default_exec_properties=rules_msbuild_image='+a.platform_image]
    else:
        cmd += ['--strategy=MSBuildAssembly=local','--strategy=TestRunner=local']
    with (folder/(case+'.log')).open('w') as log:
        result=subprocess.run(cmd,cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=900)
    assert (result.returncode==0)==success,(case,(folder/(case+'.log')).read_text()[-6000:])
    text=(folder/(case+'.execution.json')).read_text(); rows=[]; decoder=json.JSONDecoder()
    while text.strip():
        row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
        if row.get('mnemonic') in ['MSBuildAssembly','TestRunner']+bootstrap_mnemonics:rows.append({k:row.get(k) for k in ['mnemonic','targetLabel','runner','cacheHit','exitCode']})
    records.append(dict(case=case,exitCode=result.returncode,actions=rows))
    print(case,rows,flush=True)
    return rows

def hashes():
    return {str(p.relative_to(w/'bazel-bin')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((w/'bazel-bin').rglob('*')) if p.is_file() and not p.name.endswith('.params') and any(x.endswith(('.runtime','.reference')) for x in p.parts)}
rows=run('local',remote=False); baseline=hashes()
assert rows and all(r['runner'] == 'local' for r in rows if r['mnemonic'] not in bootstrap_mnemonics),rows
# A new output base and disabled remote reads force actual remote execution.
rows=run('remote',fresh=True)
assert rows and all(r['runner']=='remote' and not r['cacheHit'] for r in rows),rows
assert {r['targetLabel'] for r in rows if r['mnemonic']=='MSBuildAssembly'}=={'//:Library','//:Tests'},rows
assert hashes()==baseline, 'Local and remote products differ'
assert set(bootstrap_mnemonics).issubset({r['mnemonic'] for r in rows}), rows
reference=hashlib.sha256((w/'bazel-bin/Library.reference/Library.dll').read_bytes()).hexdigest()
assert reference==baseline['Library.reference/Library.dll']
# Use the same remote output base for incremental invalidation.
put('Value.cs','public static class Value { public static int Get() => 11; }');put('expected.txt','11:resource')
rows=run('body-edit',fresh=True,cached=True)
assert {r['targetLabel'] for r in rows if r['mnemonic']=='MSBuildAssembly' and not r['cacheHit']}=={'//:Library'},rows
assert any(r['mnemonic']=='TestRunner' and r['runner']=='remote' and not r['cacheHit'] for r in rows),rows
assert hashlib.sha256((w/'bazel-bin/Library.reference/Library.dll').read_bytes()).hexdigest()==reference
expected=hashes()
# Delete only this harness's output base; recovery must consult the remote cache.
import shutil
shutil.rmtree(folder/'recovery-base')
rows=run('recover',fresh=True,cached=True)
assert rows and all(r['cacheHit'] for r in rows),rows
assert hashes()==expected
put('expected.txt','incorrect')
rows=run('test-failure',fresh=True,cached=True,success=False)
assert any(r['mnemonic']=='TestRunner' and r['runner']=='remote' and not r['cacheHit'] and r['exitCode']!=0 for r in rows),rows
put('expected.txt','11:resource')
put('Value.cs','public static class Value { public static int Get() => 12; }')
rows=run('unavailable-executor',fresh=True,success=False,unavailable=True)
assert not any(r['runner'] in ['local','worker','linux-sandbox','processwrapper-sandbox'] for r in rows),rows
(folder/'report.json').write_text(json.dumps(dict(versions=versions,downloadedSdk=a.download_sdk,records=records,outputHashes=expected),indent=2)+'\n')
