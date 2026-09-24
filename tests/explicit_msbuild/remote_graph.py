"""Remote diamond, declared NuGet content, and MSBuild task invalidation controls."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--platform-image', default='47a9e2fed018-sdk-removed')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
folder = a.output.resolve(); folder.mkdir(parents=True)
w = folder/'source'; w.mkdir()
bazel = os.environ['RULES_MSBUILD_BAZEL']
version = subprocess.check_output([bazel, '--version'], text=True).strip()

def put(name, value):
    path = w/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)

put('MODULE.bazel', f'''module(name="remote_graph")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",version="10.0.400",platforms=["linux-arm64"])
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
def library(name, source, deps=(), extra=''):
    references = ''.join('<ProjectReference Include="'+d+'.csproj" />' for d in deps)
    put(name+'.csproj', project.format('', '<ItemGroup>'+references+'</ItemGroup>'+extra))
    put(name+'.cs', source)

shared = 'public static class Shared { public static int Value() => 1; }'
library('Shared', shared)
library('Left', 'public static class Left { public static int Value() => Shared.Value()+PackageContent.Value(); }', ['Shared'], '<ItemGroup><PackageReference Include="Fixture.Content" Version="1.0.0" /></ItemGroup>')
library('Right', 'public static class Right { public static int Value() => Shared.Value(); }', ['Shared'])
library('Tasks', '''using Microsoft.Build.Framework;
public class Generate : ITask {
 public IBuildEngine BuildEngine { get; set; } = null!;
 public ITaskHost HostObject { get; set; } = null!;
 [Required] public string OutputFile { get; set; } = null!;
 public bool Execute() { System.IO.File.WriteAllText(OutputFile, "internal static class Generated { internal static int Value() => 1; }"); return true; }
}''', extra='<ItemGroup><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false" /></ItemGroup>')
put('Tests.csproj', project.format('<OutputType>Exe</OutputType><TaskLocation>/missing-task/Tasks.dll</TaskLocation>', '''<ItemGroup><ProjectReference Include="Left.csproj"/><ProjectReference Include="Right.csproj"/><ProjectReference Include="Tasks.csproj" ReferenceOutputAssembly="false" /></ItemGroup><UsingTask TaskName="Generate" AssemblyFile="$(TaskLocation)"/><Target Name="GenerateSource" BeforeTargets="CoreCompile"><Generate OutputFile="$(IntermediateOutputPath)Generated.cs"/><ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs"/></ItemGroup></Target>'''))
put('Tests.cs', 'return (Left.Value()+Right.Value()+Generated.Value()).ToString()==System.IO.File.ReadAllText("expected.txt") ? 0 : 1;')
put('LeftTest.csproj', project.format('<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="Left.csproj"/></ItemGroup>'))
put('LeftTest.cs', 'return Left.Value().ToString()==System.IO.File.ReadAllText("left-expected.txt") ? 0 : 1;')
put('expected.txt','8'); put('left-expected.txt','6')

build = '''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test","msbuild_tool","msbuild_file_binding","msbuild_nuget_package")
'''
for name, deps in [('Shared',[]),('Left',[':Shared',':package']),('Right',[':Shared']),('Tasks',[])]:
    build += f'msbuild_library(name="{name}",project="{name}.csproj",srcs=["{name}.cs"],deps={json.dumps(deps)},target_framework="net10.0",linux_worker=True,allow_remote_execution=True)\n'
build += '''msbuild_tool(name="task_tool",assembly=":Tasks")
msbuild_file_binding(name="task_binding",tool=":task_tool",property_name="TaskLocation")
msbuild_test(name="Tests",project="Tests.csproj",srcs=["Tests.cs"],deps=[":Left",":Right"],tools=[":task_tool"],bindings=[":task_binding"],data=["expected.txt"],target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
msbuild_test(name="LeftTest",project="LeftTest.csproj",srcs=["LeftTest.cs"],deps=[":Left"],data=["left-expected.txt"],target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
'''

def package(value, binding=True):
    archive=w/'content.nupkg'
    with zipfile.ZipFile(archive,'w') as z:
        contents = {'Fixture.Content.nuspec': '<package><metadata><id>Fixture.Content</id><version>1.0.0</version><authors>Fixture</authors><description>Remote input control</description><contentFiles><files include="cs/any/Content.cs" buildAction="Compile" /></contentFiles></metadata></package>', 'contentFiles/cs/any/Content.cs': 'internal static class PackageContent { internal static int Value() => '+str(value)+'; }'}
        for name,text in contents.items(): z.writestr(zipfile.ZipInfo(name, (2020,1,1,0,0,0)),text)
    data=archive.read_bytes()
    declaration=f'msbuild_nuget_package(name="package",package_id="Fixture.Content",version="1.0.0",archive="content.nupkg",archive_sha256="{hashlib.sha256(data).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}")\n'
    put('BUILD.bazel', (build if binding else build.replace('bindings=[":task_binding"]','bindings=[]'))+declaration)
package(5)
records=[]
base=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']

def run(case, expected, *, cold=False, error=None, test_count=2):
    execution=folder/(case+'.execution.json')
    cmd=base+['test','//:Tests','//:LeftTest','--keep_going','--jobs=2','--lockfile_mode=off','--disk_cache=','--remote_executor='+a.executor,'--remote_cache='+a.executor,'--remote_instance_name=graph/'+folder.name,'--noremote_local_fallback','--spawn_strategy=remote','--strategy=MSBuildAssembly=remote','--remote_accept_cached='+str(not cold).lower(),'--remote_upload_local_results=false','--remote_download_outputs=all','--remote_default_exec_properties=ISA=aarch64','--remote_default_exec_properties=OSFamily=linux','--remote_default_exec_properties=rules_msbuild_image='+a.platform_image,'--test_output=errors','--execution_log_json_file='+str(execution)]
    result=subprocess.run(cmd,cwd=w,text=True,capture_output=True,timeout=900)
    output=result.stdout+result.stderr;(folder/(case+'.log')).write_text(output)
    assert (result.returncode!=0)==bool(error),(case,output[-6000:])
    if error: assert error in output,(case,output[-6000:])
    actions=[];data=execution.read_text().strip();decoder=json.JSONDecoder()
    while data:
        row,end=decoder.raw_decode(data);actions.append(row);data=data[end:].lstrip()
    relevant=[r for r in actions if r.get('mnemonic') in ['MSBuildAssembly','MSBuildNugetExtract','MSBuildRunnerBootstrap','TestRunner','DotnetSdkRuntime']]
    assert all(r.get('runner') in ['remote','remote cache hit'] for r in relevant), relevant
    if cold: assert all(not r.get('cacheHit') for r in relevant), relevant
    compiled=sorted(r['targetLabel'] for r in relevant if r['mnemonic']=='MSBuildAssembly' and not r.get('cacheHit'))
    assert compiled==expected,(case,compiled)
    tests=sorted({r['targetLabel'] for r in relevant if r['mnemonic']=='TestRunner' and not r.get('cacheHit')})
    assert len(tests)==test_count,(case,tests)
    row=dict(case=case,compiled=compiled,testsExecuted=tests,actions=[{k:r.get(k) for k in ['mnemonic','targetLabel','runner','cacheHit','exitCode']} for r in relevant])
    records.append(row);(folder/'report.json').write_text(json.dumps(dict(bazel=version,cases=records),indent=2)+'\n');print(json.dumps(row),flush=True)
    return relevant

def ref(): return hashlib.sha256((w/'bazel-bin/Shared.reference/Shared.dll').read_bytes()).hexdigest()
try:
    rows=run('cold',['//:Left','//:LeftTest','//:Right','//:Shared','//:Tasks','//:Tests'],cold=True)
    assert any(r['mnemonic']=='MSBuildNugetExtract' for r in rows)
    before=ref()
    run('noop',[],test_count=0)
    put('Shared.cs',shared.replace('=> 1','=> 2'));put('expected.txt','10');put('left-expected.txt','7')
    run('body',['//:Shared']);assert ref()==before
    put('Shared.cs',shared.replace('=> 1','=> 2').replace(' }',' public static int Added() => 0; }'))
    run('api',['//:Left','//:LeftTest','//:Right','//:Shared','//:Tests']);assert ref()!=before
    package(7);put('expected.txt','12');put('left-expected.txt','9')
    run('package-edit',['//:Left','//:LeftTest','//:Tests'])
    put('Tasks.cs',(w/'Tasks.cs').read_text().replace('=> 1','=> 2'));put('expected.txt','13')
    run('task-edit',['//:Tasks','//:Tests'],test_count=1)
    package(7,binding=False)
    run('missing-binding',['//:Tests'],error='missing-task',test_count=0)
    package(7)
    run('restored',[],test_count=0)
    products = lambda: {str(p.relative_to(w/'bazel-bin')): hashlib.sha256(p.read_bytes()).hexdigest() for p in (w/'bazel-bin').glob('*.runtime/*.dll')}
    before_recovery = products()
    subprocess.run(base+['shutdown'],cwd=w,check=True)
    base = [bazel,'--output_base='+str(folder/'recovery-base'),'--ignore_all_rc_files']
    recovered = run('fresh-recovery',[],test_count=0)
    assert recovered and all(r.get('cacheHit') for r in recovered), recovered
    assert any(r['mnemonic']=='MSBuildNugetExtract' for r in recovered), recovered
    assert products()==before_recovery

finally:
    subprocess.run(base+['shutdown'],cwd=w,check=True)
