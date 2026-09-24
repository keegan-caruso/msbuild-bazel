"""Project output content and explicit framework-assembly contract controls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

rules=Path(__file__).resolve().parents[2]
folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True)
workspace=folder/'src';workspace.mkdir()
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL']
(workspace/'MODULE.bazel').write_text(f'''module(name="project_outputs")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(rules))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
header='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_binary","msbuild_project_output")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="Plugin",project="Plugin/Plugin.csproj",srcs=["Plugin/Plugin.cs"],target_framework="net10.0",linux_worker=True)
msbuild_project_output(name="content",assembly=":Plugin",item_type="Content",metadata={"CopyToOutputDirectory":"PreserveNewest"})
msbuild_binary(name="App",project="App/App.csproj",srcs=["App/Program.cs"],target_framework="net10.0",project_outputs=[":content"],framework_assemblies=["System.Text.Json"],use_apphost=False,linux_worker=True)
'''
(workspace/'BUILD.bazel').write_text(header)
for directory in ['App','Plugin']:(workspace/directory).mkdir()
(workspace/'Plugin/Plugin.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(workspace/'Plugin/Plugin.cs').write_text('public class Plugin { public static string Value() => "first"; }')
project='''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Plugin/Plugin.csproj" ReferenceOutputAssembly="false" OutputItemType="Content" CopyToOutputDirectory="PreserveNewest"/><Reference Include="System.Text.Json"/></ItemGroup></Project>'''
(workspace/'App/App.csproj').write_text(project)
(workspace/'App/Program.cs').write_text('var a=System.Reflection.Assembly.LoadFrom(System.IO.Path.Combine(System.AppContext.BaseDirectory,"Plugin.dll"));System.Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(a.GetType("Plugin")!.GetMethod("Value")!.Invoke(null,null)));')
startup=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
flags=['--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--remote_download_outputs=all']
reports=[]
def run(case, expected=None, error=None):
    p=subprocess.run(startup+['run','//:App']+flags,cwd=workspace,capture_output=True,text=True,timeout=240)
    (folder/(case+'.log')).write_text(p.stdout+p.stderr)
    if error: assert p.returncode and error in p.stderr,(case,p.stderr[-4000:])
    else: assert p.returncode==0 and p.stdout.strip()==json.dumps(expected),(case,p.stdout,p.stderr[-4000:])
    reports.append({'case':case,'exitCode':p.returncode});print(case,p.returncode,flush=True)
try:
    run('initial','first')
    assert not (workspace/'bazel-bin/App.runtime/App').exists(), 'Apphost must follow the explicit setting'
    reference=workspace/'bazel-bin/App.reference/App.dll';before=hashlib.sha256(reference.read_bytes()).hexdigest()
    (workspace/'Plugin/Plugin.cs').write_text('public class Plugin { public static string Value() => "second"; }')
    run('implementation-edit','second');assert hashlib.sha256(reference.read_bytes()).hexdigest()==before
    (workspace/'BUILD.bazel').write_text(header.replace('framework_assemblies=["System.Text.Json"]','framework_assemblies=[]'))
    run('undeclared-framework',error='Undeclared assembly/analyzer dependency: System.Text.Json')
    (workspace/'BUILD.bazel').write_text(header.replace('System.Text.Json','Not.A.Framework.Assembly'))
    (workspace/'App/App.csproj').write_text(project.replace('System.Text.Json','Not.A.Framework.Assembly'))
    run('unknown-framework-assembly',error='Assembly is not in a declared framework reference pack')
    (workspace/'BUILD.bazel').write_text(header);(workspace/'App/App.csproj').write_text(project.replace('<Reference Include="System.Text.Json"/>', ''))
    run('framework-without-reference',error='Framework assembly requires a matching Reference')
    (workspace/'BUILD.bazel').write_text(header);(workspace/'App/App.csproj').write_text(project.replace('CopyToOutputDirectory="PreserveNewest"','CopyToOutputDirectory="Always"'))
    run('copy-metadata-mismatch',error='Project output metadata disagrees')
    (workspace/'App/App.csproj').write_text(project.replace('OutputItemType="Content"','OutputItemType="Analyzer"'))
    run('role-mismatch',error='Project output role disagrees')
    (workspace/'App/App.csproj').write_text(project)
    (workspace/'BUILD.bazel').write_text(header.replace('project_outputs=[":content"]','project_outputs=[]'))
    run('missing-project-output',error='ProjectReference declarations disagree')
    (workspace/'BUILD.bazel').write_text(header);run('recovered','second')
    contract_header=header.replace('srcs=["Plugin/Plugin.cs"],','srcs=["Plugin/Plugin.cs"],output_mode="reference",').replace('item_type="Content",metadata={"CopyToOutputDirectory":"PreserveNewest"}', 'item_type="ContractInput",artifact="reference"')
    contract_project=project.replace('OutputItemType="Content" CopyToOutputDirectory="PreserveNewest"', 'OutputItemType="ContractInput" SetConfiguration="Configuration=Release"').replace('</Project>', '''<Target Name="CheckContract" BeforeTargets="CoreCompile"><Error Condition="'@(ContractInput)' == ''" Text="Missing contract input"/><GetAssemblyIdentity AssemblyFiles="@(ContractInput)"><Output TaskParameter="Assemblies" ItemName="_ContractIdentity"/></GetAssemblyIdentity><Error Condition="'%(_ContractIdentity.Version)' != '1.0.0.0'" Text="Wrong contract version"/></Target></Project>''')
    (workspace/'BUILD.bazel').write_text(contract_header)
    (workspace/'App/App.csproj').write_text(contract_project)
    (workspace/'App/Program.cs').write_text('System.Console.WriteLine(System.Text.Json.JsonSerializer.Serialize("contract"));')
    run('custom-contract-output','contract')
    assert not list((workspace/'bazel-bin/Plugin.runtime').iterdir())
    assert not (workspace/'bazel-bin/App.runtime/Plugin.dll').exists()
    (workspace/'App/App.csproj').write_text(contract_project.replace('Configuration=Release','Configuration=Debug'))
    run('contract-configuration-mismatch',error='Configured ProjectReference disagrees')
    (workspace/'App/App.csproj').write_text(contract_project)
    (workspace/'BUILD.bazel').write_text(contract_header.replace('item_type="ContractInput"','item_type="Reference"'))
    run('reserved-contract-item',error='Project output items cannot replace dependency/source declarations')
    (workspace/'BUILD.bazel').write_text(contract_header)
    run('custom-contract-recovered','contract')
finally: subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
(folder/'report.json').write_text(json.dumps(reports,indent=2)+'\n')
