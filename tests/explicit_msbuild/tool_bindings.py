"""Real MSBuild task, dependency edits, binding failures and independent cache recovery."""
import base64,hashlib,json,os,shutil,subprocess,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True)
mixed='--mixed-roles' in sys.argv
workspace=folder/'src';workspace.mkdir();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];base=folder/'base'
def put(path,text):
 p=workspace/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
put('MODULE.bazel',f'''module(name="tool_bindings")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
put('BUILD.bazel','''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''')
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
put('Helper/Helper.csproj',project.format('',''))
put('Helper/Helper.cs','public static class Helper { public static string Value() => "first"; }')
put('Helper/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")
msbuild_library(name="Helper",project="Helper.csproj",target_framework="net10.0",srcs=["Helper.cs"],linux_worker=True,visibility=["//visibility:public"])
''')
put('Tasks/Tasks.csproj',project.format('','<ItemGroup><ProjectReference Include="../Helper/Helper.csproj"/><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false"/></ItemGroup>'))
put('Tasks/Tasks.cs','''using Microsoft.Build.Framework;
public class Generate : ITask {
 public IBuildEngine BuildEngine { get; set; } = null!;
 public ITaskHost HostObject { get; set; } = null!;
 [Required] public string OutputFile { get; set; } = null!;
 public bool Execute() { if (System.IO.Path.GetFileName(System.IO.Path.GetDirectoryName(typeof(Generate).Assembly.Location)) != "net") return false; System.IO.File.WriteAllText(OutputFile, "internal static class Generated { internal static string Value() => \\\"" + Helper.Value() + "\\\"; }"); return true; }
}
''')
put('Tasks/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_tool","msbuild_file_binding")
msbuild_library(name="Tasks",project="Tasks.csproj",target_framework="net10.0",srcs=["Tasks.cs"],deps=["//Helper"],linux_worker=True)
msbuild_tool(name="tool",assembly=":Tasks",layout_prefix="net",visibility=["//visibility:public"])
msbuild_file_binding(name="binding",tool=":tool",property_name="BuildTasksLocation",visibility=["//visibility:public"])
''')
app_project=project.format('<OutputType>Exe</OutputType><BuildTasksLocation>/deliberately/wrong.dll</BuildTasksLocation><RuntimeIdentifierGraphPath>$(MSBuildProjectDirectory)/runtime.json</RuntimeIdentifierGraphPath>', '''<ItemGroup><ProjectReference Include="../Tasks/Tasks.csproj" ReferenceOutputAssembly="false" SetConfiguration="Configuration=Release" SetTargetFramework="TargetFramework=net10.0" PrivateAssets="all"/></ItemGroup><UsingTask TaskName="Generate" AssemblyFile="$(BuildTasksLocation)" TaskFactory="TaskHostFactory"/><Target Name="GenerateSource" BeforeTargets="CoreCompile"><Generate OutputFile="$(IntermediateOutputPath)Generated.cs"/><ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs"/></ItemGroup></Target>''')
put('App/runtime.json','{"runtimes":{}}')
put('App/App.csproj',app_project);put('App/Program.cs','System.Console.WriteLine(Generated.Value());')
app_build='''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")
msbuild_binary(name="App",project="App.csproj",msbuild_imports=["runtime.json"],target_framework="net10.0",srcs=["Program.cs"],tools=["//Tasks:tool"],bindings=["//Tasks:binding"],linux_worker=True)
'''
put('App/BUILD.bazel',app_build)
if mixed:
 archive=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/netstandard.library.ref/2.1.0/netstandard.library.ref.2.1.0.nupkg').read()
 digest=hashlib.sha256(archive).hexdigest();assert digest=='46ea2fcbd10a817685b85af7ce0c397d12944bdc81209e272de1e05efd33c78a'
 (workspace/'Helper/ref.nupkg').write_bytes(archive)
 helper=(workspace/'Helper/BUILD.bazel').read_text().replace('"msbuild_library")','"msbuild_library","msbuild_nuget_package","msbuild_package_lock")').replace('name="Helper",','name="Helper",package_lock=":lock",')
 helper+=f'msbuild_nuget_package(name="ref",package_id="NETStandard.Library.Ref",version="2.1.0",archive="ref.nupkg",archive_sha256="{digest}",content_hash="{base64.b64encode(hashlib.sha512(archive).digest()).decode()}")\nmsbuild_package_lock(name="lock",packages=[":ref"])\n'
 put('Helper/BUILD.bazel',helper)
 for name in ['Helper/Helper.csproj','Helper/BUILD.bazel']:
  put(name,(workspace/name).read_text().replace('net10.0','netstandard2.1'))
 put('Tasks/BUILD.bazel',(workspace/'Tasks/BUILD.bazel').read_text().replace('deps=["//Helper"],linux_worker=True','deps=["//Helper"],linux_worker=True,visibility=["//visibility:public"]'))
 app_project=app_project.replace('ReferenceOutputAssembly="false"','ReferenceOutputAssembly="true"')
 app_build=app_build.replace('tools=[','deps=["//Tasks:Tasks"],tools=[')
 put('App/App.csproj',app_project);put('App/BUILD.bazel',app_build)
 put('App/Program.cs','System.Console.WriteLine(Generated.Value() + ":" + Helper.Value());')
startup=[bazel,'--output_base='+str(base),'--ignore_all_rc_files'];flags=['--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'];rows=[]
def run(case,expected=None,error=None):
 if mixed and expected is not None:expected += ":"+expected
 p=subprocess.run(startup+['run','//App','--execution_log_json_file='+str(folder/(case+'.execution.json'))]+flags,cwd=workspace,capture_output=True,text=True,timeout=240)
 output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
 assert (p.returncode==0 and p.stdout.strip()==expected) if error is None else p.returncode!=0 and error in output,(case,output[-5000:])
 rows.append(dict(case=case,exit=p.returncode));print(case,p.returncode,flush=True)
def refs():return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (base/'execroot/_main/bazel-out').glob('*/bin/**/*.reference/*.dll') if p.name in ('Helper.dll','Tasks.dll')}
try:
 run('initial','first')
 task_build=(workspace/'Tasks/BUILD.bazel').read_text()
 put('Tasks/BUILD.bazel',task_build.replace('layout_prefix="net"','layout_prefix="../net"'))
 run('unsafe-layout-prefix',error='Tool layout_prefix must be a safe relative path')
 put('Tasks/BUILD.bazel',task_build)
 put('App/BUILD.bazel',app_build.replace('linux_worker=True','msbuild_properties={"NetCoreSdkRoot":"/undeclared-sdk"},linux_worker=True'))
 run('sdk-root-override',error='Reserved or file-valued MSBuild property')
 put('App/BUILD.bazel',app_build)
 for property_name, before_value, after_value in [('configuration', 'Configuration=Release', 'Configuration=Debug'), ('framework', 'TargetFramework=net10.0', 'TargetFramework=net9.0')]:
  put('App/App.csproj',app_project.replace(before_value, after_value))
  run('tool-'+property_name+'-mismatch',error='Configured ProjectReference disagrees')
 put('App/App.csproj',app_project)
 run('configured-tool-recovered','first');before=refs();assert {'Helper.dll','Tasks.dll'}<=before.keys()
 runtime=next((base/'execroot/_main/bazel-out').glob('*/bin/App/App.runtime'))
 assert not (runtime/'Tasks.dll').exists() and not (runtime/'Helper.dll').exists()
 put('Helper/Helper.cs','public static class Helper { public static string Value() => "second"; }')
 run('tool-dependency-body-edit','second');after=refs();assert before==after,(before,after)
 text=(folder/'tool-dependency-body-edit.execution.json').read_text();decoder=json.JSONDecoder();executed=[]
 while text.strip():
  row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if row.get('mnemonic')=='MSBuildAssembly' and not row.get('cacheHit'):executed.append(row)
 assert len(executed)==(3 if mixed else 2),len(executed)
 put('App/App.csproj',app_project.replace('ReferenceOutputAssembly="true"','ReferenceOutputAssembly="false"') if mixed else app_project.replace('ReferenceOutputAssembly="false"','ReferenceOutputAssembly="true"'))
 run('wrong-role',error='analyzer role disagrees');put('App/App.csproj',app_project)
 put('App/BUILD.bazel',app_build.replace('tools=["//Tasks:tool"]','tools=[]'))
 run('undeclared-tool',error='Bound tool must also be declared');put('App/BUILD.bazel',app_build)
 task_build=(workspace/'Tasks/BUILD.bazel').read_text()
 put('Tasks/BUILD.bazel',task_build.replace('property_name="BuildTasksLocation"','property_name="OutputPath"'))
 run('reserved-property',error='Reserved or conflicting bound property')
 put('Tasks/BUILD.bazel',task_build.replace('assembly=":Tasks"','assembly=":Tasks",entry_point="missing.dll"'))
 run('missing-entry',error='Missing build tool entry')
 put('Tasks/BUILD.bazel',task_build.replace('assembly=":Tasks"','assembly=":Tasks",entry_point="../Tasks.dll"'))
 run('unsafe-entry',error='safe relative file path');put('Tasks/BUILD.bazel',task_build)
 put('App/App.csproj',app_project.replace('<Project Sdk=', '<Project TreatAsLocalProperty="BuildTasksLocation" Sdk='))
 run('overridden-binding',error='Bound tool property was overridden');put('App/App.csproj',app_project)
 if mixed:
  helper_build=(workspace/'Helper/BUILD.bazel').read_text()
  put('Helper/BUILD.bazel',helper_build.replace('netstandard2.1','net10.0'))
  put('Tasks/BUILD.bazel',task_build.replace('target_framework="net10.0"','target_framework="netstandard2.1"'))
  run('incompatible-framework',error='Incompatible explicit project frameworks')
  put('Helper/BUILD.bazel',helper_build);put('Tasks/BUILD.bazel',task_build)
 run('recovered','second')
 subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
 relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*'))
 shutil.rmtree(workspace);shutil.rmtree(base);workspace=relocated;startup=[bazel,'--output_base='+str(folder/'fresh-base'),'--output_user_root='+str(folder/'fresh-user'),'--ignore_all_rc_files']
 run('deleted-producer-cache-recovery','second')
 text=(folder/'deleted-producer-cache-recovery.execution.json').read_text();cached=[]
 while text.strip():
  row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if row.get('mnemonic')=='MSBuildAssembly':cached.append(row)
 assert len(cached)==(5 if mixed else 3) and all(r.get('cacheHit') for r in cached),cached
finally:
 subprocess.run(startup+['shutdown'],cwd=workspace)
(folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
