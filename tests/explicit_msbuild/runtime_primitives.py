"""Small runtime repository capabilities: contracts, configurations, layouts and hosts."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL=os.environ['RULES_MSBUILD_BAZEL']
folder=Path(sys.argv[1]).resolve(); folder.mkdir(parents=True)
workspace=folder/'source'; workspace.mkdir()
records=[]
def put(path,text):
    dest=workspace/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
put('MODULE.bazel',f'''module(name="runtime_primitives")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(SDK))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
header='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test","msbuild_assembly","msbuild_layout","msbuild_runtime","msbuild_reference_pack","msbuild_generate","msbuild_items")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="contract",project="ref/Contract.csproj",assembly_name="Pair",srcs=["ref/Code.cs"],target_framework="net10.0",output_mode="reference",linux_worker=True)
msbuild_library(name="impl",project="src/Impl.csproj",assembly_name="Pair",srcs=["src/Code.cs"],target_framework="net10.0",output_mode="implementation",configuration="Release",msbuild_properties={"Feature":"Chosen"},linux_worker=True)
msbuild_assembly(name="pair",contract=":contract",implementation=":impl")
msbuild_test(name="consumer",project="app/App.csproj",assembly_name="App",srcs=["app/Code.cs"],target_framework="net10.0",configuration="Debug",deps=[":pair"],use_apphost=False,linux_worker=True)
'''
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
put('ref/Contract.csproj',project.format(''))
put('src/Impl.csproj',project.format(''))
app=project.format('<ItemGroup><ProjectReference Include="../src/Impl.csproj" SetConfiguration="Configuration=Release" SetTargetFramework="TargetFramework=net10.0" AdditionalProperties="Feature=Chosen"/></ItemGroup>')
put('app/App.csproj',app)
contract='public static class Api { public static int Read() => throw null; }'
impl='public static class Api { public static int Read() => 7; internal static int Secret() => 4; }'
consumer='System.Console.WriteLine(Api.Read()); return Api.Read() == 7 ? 0 : 1;'
put('ref/Code.cs',contract);put('src/Code.cs',impl);put('app/Code.cs',consumer);put('BUILD.bazel',header)
startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files']
def run(case,error=None,target='//:consumer',force=False):
    execution=folder/(case+'.execution.json')
    p=subprocess.run(startup+['build' if target=='//:core' else 'test',target,'--test_output=all','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache='+str(folder/'cache'),'--execution_log_json_file='+str(execution)]+(['--nocache_test_results'] if force else []),cwd=workspace,capture_output=True,text=True,timeout=240)
    output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
    assert (p.returncode==0)==(error is None),(case,output[-6000:])
    if error: assert error in output,(case,error,output[-6000:])
    rows=[];text=execution.read_text() if execution.exists() else '';decoder=json.JSONDecoder()
    while text.strip():
        row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:];rows.append(row)
    compiled=sorted(r['targetLabel'] for r in rows if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit'))
    record={'case':case,'exitCode':p.returncode,'compiled':compiled,'testExecuted':any(r.get('mnemonic')=='TestRunner' and not r.get('cacheHit') for r in rows),'executedActions':[r['mnemonic']+':'+r['targetLabel'] for r in rows if r.get('mnemonic','').startswith('MSBuild') and not r.get('cacheHit')]};records.append(record)
    print(json.dumps(record),flush=True);(folder/'report.json').write_text(json.dumps(records,indent=2)+'\n')
    return record
try:
    put('chain/Chain.csproj',project.format('<ItemGroup><ProjectReference Include="../ref/Contract.csproj" /></ItemGroup>'))
    put('chain/Code.cs','public class UsesContract { public int Read() => Api.Read(); }')
    put('BUILD.bazel',header+'\nmsbuild_library(name="core",project="chain/Chain.csproj",srcs=["chain/Code.cs"],assembly_name="Chain",target_framework="net10.0",output_mode="reference",deps=[":contract"],msbuild_properties={"UseSharedCompilation":"false"},linux_worker=True)\n')
    run('reference-only-chain',target='//:core')
    assert not list((workspace/'bazel-bin/core.runtime').iterdir())
    chain_build=(workspace/'BUILD.bazel').read_text()
    put('BUILD.bazel',chain_build.replace('"UseSharedCompilation":"false"','"UseSharedCompilation":"invalid"'))
    run('invalid-shared-compilation',error='Reserved or file-valued MSBuild property: UseSharedCompilation',target='//:core')
    put('BUILD.bazel',header)
    run('contract-implementation')
    assert not list((workspace/'bazel-bin/contract.runtime').iterdir()),'Contract must not enter runtime closure'
    put('src/Code.cs',impl.replace('=> 7','=> 8'))
    r=run('implementation-body',error='FAIL');assert r['compiled']==['//:impl'],r
    put('src/Code.cs',impl);run('body-recovery')
    put('ref/Code.cs',contract.replace('Read()', 'Read(int n)'))
    run('contract-api',error='CS7036');put('ref/Code.cs',contract)
    put('app/App.csproj',app.replace('Configuration=Release','Configuration=Debug'))
    run('configuration-mismatch',error='Configured ProjectReference disagrees')
    put('app/App.csproj',app.replace('Feature=Chosen','Feature=Other'))
    run('feature-mismatch',error='Configured ProjectReference disagrees')
    put('app/App.csproj',app)
    put('BUILD.bazel',header.replace('assembly_name="Pair",srcs=["src', 'assembly_name="Wrong",srcs=["src'))
    run('identity-mismatch',error='assembly name/framework must match')
    put('BUILD.bazel',header.replace('deps=[":pair"]','deps=[":contract"]'))
    run('unpaired-contract',error='Reference-only dependencies require')
    put('BUILD.bazel',header);run('recovered')

    put('src/Impl.csproj',project.format('<PropertyGroup><AssemblyVersion>2.0.0.0</AssemblyVersion></PropertyGroup>'))
    run('assembly-version-mismatch',error='assembly identity mismatch');put('src/Impl.csproj',project.format(''))
    put('src/Code.cs','[assembly: System.Runtime.CompilerServices.InternalsVisibleTo("App")]\n'+impl)
    put('app/Code.cs','return Api.Secret()==4 ? 0 : 1;')
    run('friend-hidden-by-contract',error='CS0117')
    put('BUILD.bazel',header.replace('deps=[":pair"]','deps=[":impl"]'))
    run('friend-implementation-edge')
    put('src/Code.cs',impl);put('app/Code.cs',consumer);put('BUILD.bazel',header)
    configured=header.replace('name="consumer",','name="consumer",msbuild_properties={"ConsumerOnly":"yes"},')
    put('BUILD.bazel',configured)
    put('app/App.csproj',app.replace('SetConfiguration=', 'GlobalPropertiesToRemove="ConsumerOnly" SetConfiguration='))
    run('removed-global-property')
    put('BUILD.bazel',configured.replace('"Feature":"Chosen"','"Feature":"Chosen","ConsumerOnly":"yes"'))
    run('removed-property-mismatch',error='removal disagrees')
    put('app/App.csproj',app);put('BUILD.bazel',header)
    # Distinct Debug/Release nodes for the same project can be selected explicitly.
    release=header.replace('configuration="Release"','configuration="Debug"')
    put('BUILD.bazel',release);put('app/App.csproj',app.replace('Configuration=Release','Configuration=Debug'))
    run('changed-producer-configuration')
    put('BUILD.bazel',header);put('app/App.csproj',app)

    put('dest/Dest.csproj',project.format(''));put('dest/Code.cs','public static class Forwarded { public static int Read()=>7; }')
    forward_project=project.format('<ItemGroup><ProjectReference Include="../dest/Dest.csproj"/></ItemGroup>')
    forward_attribute='[assembly: System.Runtime.CompilerServices.TypeForwardedTo(typeof(Forwarded))]\n'
    put('ref/Contract.csproj',forward_project);put('src/Impl.csproj',forward_project)
    put('ref/Code.cs',forward_attribute+contract);put('src/Code.cs',forward_attribute+impl)
    forward_build=header.replace('name="contract",','name="contract",deps=[":dest"],').replace('name="impl",','name="impl",deps=[":dest"],')+'msbuild_library(name="dest",project="dest/Dest.csproj",srcs=["dest/Code.cs"],target_framework="net10.0",linux_worker=True)\n'
    put('BUILD.bazel',forward_build);put('app/Code.cs','return Forwarded.Read()==7 ? 0 : 1;')
    run('type-forwarder')
    put('dest/Code.cs','public static class Forwarded { public static int Read()=>8; }')
    row=run('forwarded-implementation-body',error='FAIL');assert row['compiled']==['//:dest'],row
    put('BUILD.bazel',header);put('app/Code.cs',consumer);put('src/Code.cs',impl);put('ref/Code.cs',contract)
    put('ref/Contract.csproj',project.format(''));put('src/Impl.csproj',project.format(''))
    put('src/Impl.csproj',project.format('<PropertyGroup><Feature>Overridden</Feature></PropertyGroup>').replace('<Project Sdk=', '<Project TreatAsLocalProperty="Feature" Sdk='))
    run('producer-property-override',error='Explicit producer property was overridden')
    put('src/Impl.csproj',project.format(''))
    put('ref/Code.cs','[assembly: System.Runtime.CompilerServices.ReferenceAssembly]\n'+contract)
    run('authored-reference-attribute');put('ref/Code.cs',contract)
    # A copied runtime host is selected independently of the SDK used to compile.
    runtime=workspace/'host-input'
    for relative in ['dotnet','host','shared/Microsoft.NETCore.App']:
        source=SDK/relative; dest=runtime/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if source.is_dir():shutil.copytree(source,dest)
        else:shutil.copy2(source,dest)
    put('host-input/witness.txt','first')
    paths={str(p.relative_to(workspace)):str(p.relative_to(runtime)) for p in runtime.rglob('*') if p.is_file()}
    hosts='msbuild_layout(name="host_tree",paths='+json.dumps(paths)+')\nmsbuild_runtime(name="host",layout=":host_tree",entry_point="dotnet")\n'
    runtime_build=header.replace('name="consumer",','name="consumer",runtime_host=":host",')+hosts
    runtime_code='''var path=typeof(object).Assembly.Location;
var root=System.IO.Path.GetFullPath(System.IO.Path.Combine(System.IO.Path.GetDirectoryName(path)!, "../../.."));
System.Console.WriteLine("corelib="+System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.IO.File.ReadAllBytes(path))));
System.Console.WriteLine("runtime="+root);
if(!System.Environment.GetEnvironmentVariable("DOTNET_HOST_PATH")!.Contains("host_tree",System.StringComparison.Ordinal))return 9;
foreach(System.Diagnostics.ProcessModule module in System.Diagnostics.Process.GetCurrentProcess().Modules)
 if(module.FileName.EndsWith("/libcoreclr.so",System.StringComparison.Ordinal))
  System.Console.WriteLine("native-runtime="+module.FileName+";sha256="+System.Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.IO.File.ReadAllBytes(module.FileName))));
return System.IO.File.ReadAllText(System.IO.Path.Combine(root,"witness.txt"))=="first" ? 0 : 1;'''
    put('BUILD.bazel',runtime_build);put('app/Code.cs',runtime_code);run('declared-runtime')
    put('host-input/witness.txt','second');row=run('runtime-only-mutation',error='FAIL');assert row['compiled']==[],row
    put('host-input/witness.txt','first');run('runtime-recovered')
    put('BUILD.bazel',runtime_build.replace('entry_point="dotnet"','entry_point="missing"'));run('missing-runtime',error='Missing declared runtime host')
    put('host-two.txt','second')
    alternate=dict(paths);alternate.pop('host-input/witness.txt');alternate['host-two.txt']='witness.txt'
    host_two='msbuild_layout(name="host_tree_two",paths='+json.dumps(alternate)+')\nmsbuild_runtime(name="host_two",layout=":host_tree_two",entry_point="dotnet")\n'
    put('BUILD.bazel',runtime_build.replace('runtime_host=":host"','runtime_host=":host_two"')+host_two)
    row=run('second-runtime-tree',error='FAIL');assert row['compiled']==[],row
    incomplete={key:value for key,value in paths.items() if not key.endswith('/libcoreclr.so')}
    put('BUILD.bazel',runtime_build.replace(json.dumps(paths),json.dumps(incomplete)))
    run('missing-runtime-component',error='FAIL')
    # No implicit framework: only the declared pack is visible to the compiler.
    pack=next((SDK/'packs/Microsoft.NETCore.App.Ref').iterdir())/'ref/net10.0'
    for file in pack.glob('*.dll'):
        dest=workspace/'pack'/file.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(file,dest)
    put('pack-marker/Marker.csproj',project.format(''))
    put('pack-marker/Code.cs','public static class PackMarker { public const int Value=7; }')
    packs='''msbuild_library(name="marker",project="pack-marker/Marker.csproj",srcs=["pack-marker/Code.cs"],target_framework="net10.0",linux_worker=True)
msbuild_reference_pack(name="pack",srcs=glob(["pack/*.dll"]),assemblies=[":marker"])
'''
    put('app/runtimeconfig.template.json',json.dumps({"framework":{"name":"Microsoft.NETCore.App","version":next((SDK/"shared/Microsoft.NETCore.App").iterdir()).name}}))
    packs+='msbuild_items(name="runtimeconfig",item_type="None",srcs=["app/runtimeconfig.template.json"])\n'
    pack_build=header.replace('name="consumer",','name="consumer",items=[":runtimeconfig"],reference_pack=":pack",')+packs
    put('BUILD.bazel',pack_build);put('app/Code.cs','return PackMarker.Value==7 ? 0 : 1;')
    run('explicit-framework-pack')
    put('pack-marker/Code.cs','public static class PackMarker { public const int Value=8; }')
    row=run('pack-api-mutation',error='FAIL');assert '//:consumer' in row['compiled'],row
    put('BUILD.bazel',pack_build.replace('reference_pack=":pack",',''));run('absent-pack',error='CS0103')
    put('BUILD.bazel',pack_build.replace('glob(["pack/*.dll"])','glob(["pack/*.dll"],exclude=["pack/System.Runtime.dll"])'))
    run('no-installed-pack-fallback',error='error CS')
    # A tiny no-standard-library/CoreLib-like producer compiles without installed refs.
    put('core/Core.csproj',project.format('<PropertyGroup><GenerateAssemblyInfo>false</GenerateAssemblyInfo><GenerateTargetFrameworkAttribute>false</GenerateTargetFrameworkAttribute></PropertyGroup>'))
    put('core/Code.cs','namespace System { public class Object {} public class ValueType {} public struct Void {} public struct Boolean {} public struct Int32 {} public class String {} }')
    core_rule='msbuild_library(name="core",project="core/Core.csproj",srcs=["core/Code.cs"],target_framework="net10.0",output_mode="implementation",lang_version="7.3",nullable="disable",msbuild_properties={"DisableImplicitFrameworkReferences":"true","NoStdLib":"true"},linux_worker=True)\n'
    put('BUILD.bazel',header+core_rule);run('no-standard-library',target='//:core')
    # Generate once, compose once, then bind the immutable layout during evaluation.
    put('generate/Generate.csproj',project.format('''<Target Name="Bootstrap"><WriteLinesToFile File="$(GeneratedProps)" Lines="&lt;Project&gt;&lt;PropertyGroup&gt;&lt;BootstrapValue&gt;7&lt;/BootstrapValue&gt;&lt;/PropertyGroup&gt;&lt;/Project&gt;" Overwrite="true"/></Target>'''))
    generated='''msbuild_generate(name="bootstrap",project="generate/Generate.csproj",target_framework="net10.0",targets=["Bootstrap"],outputs=["Bootstrap.props"],output_properties={"GeneratedProps":"Bootstrap.props"},linux_worker=True)
msbuild_layout(name="bootstrap_layout",paths={":bootstrap":"Bootstrap.props"})
'''
    layout_app=app.replace('</Project>','<Import Project="$(BootstrapRoot)Bootstrap.props"/><Target Name="CheckBootstrap" BeforeTargets="CoreCompile"><Error Condition="\'$(BootstrapValue)\' != \'7\'" Text="Wrong bootstrap value"/></Target></Project>')
    layout_build=header.replace('name="consumer",','name="consumer",layout_bindings={":bootstrap_layout":"BootstrapRoot"},')+generated
    put('BUILD.bazel',layout_build);put('app/App.csproj',layout_app);put('app/Code.cs',consumer)
    run('generated-layout')
    tree_layout=layout_build.replace('layout_bindings={":bootstrap_layout":','layout_bindings={":nested_layout":')+'\nmsbuild_layout(name="nested_layout",paths={":bootstrap_layout":"."})\n'
    put('BUILD.bazel',tree_layout)
    run('tree-artifact-layout')
    put('BUILD.bazel',layout_build)
    put('generate/Generate.csproj',(workspace/'generate/Generate.csproj').read_text().replace('&gt;7&lt;','&gt;8&lt;'))
    run('generated-layout-mutation',error='Wrong bootstrap value')
    put('generate/Generate.csproj',(workspace/'generate/Generate.csproj').read_text().replace('&gt;8&lt;','&gt;7&lt;'))
    put('collision.props','different')
    put('BUILD.bazel',layout_build.replace('paths={":bootstrap":"Bootstrap.props"}','paths={":bootstrap":"Bootstrap.props","collision.props":"Bootstrap.props"}'))
    run('layout-collision',error='Conflicting runtime/input destination')
    put('BUILD.bazel',layout_build.replace('"Bootstrap.props"})','"../Bootstrap.props"})'))
    run('unsafe-layout-destination',error='Unsafe logical path')
    put('BUILD.bazel',layout_build)
    generator=(workspace/'generate/Generate.csproj').read_text()
    put('generate/Generate.csproj',generator.replace('File="$(GeneratedProps)"','File="$(GeneratedProps).wrong"'))
    run('missing-generated-output',error='Missing declared generated output')
    put('generate/Generate.csproj',generator)
    put('app/App.csproj',layout_app.replace('<Error Condition=', '<WriteLinesToFile File="$(BootstrapRoot)Bootstrap.props" Lines="overwrite" Overwrite="true"/><Error Condition='))
    run('read-only-layout',error='error MSB')
    put('app/App.csproj',layout_app)
    put('BUILD.bazel',layout_build);run('layout-recovered')
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
    relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*'))
    shutil.rmtree(workspace);shutil.rmtree(folder/'base');workspace=relocated
    startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'fresh-base'),'--ignore_all_rc_files']
    row=run('producer-deleted-recovery',force=True);assert row['compiled']==[] and row['testExecuted'],row

finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
