"""Qualify original Orchard targets/manifest sources with explicit Razor inputs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

folder=Path(sys.argv[1]).resolve();workspace=folder/'src';orchard=Path(sys.argv[2]).resolve()
bazel=os.environ['RULES_MSBUILD_BAZEL'];sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
def put(name,text):
 p=workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
def copy(source,dest):
 p=workspace/dest;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(orchard/source,p)
manifest='src/OrchardCore/OrchardCore.Abstractions/Modules/Manifest/'
for name in ['FeatureAttribute','ModuleAttribute','ModuleMarkerAttribute','ModuleAssetAttribute','ModuleNameAttribute']:
 copy(manifest+name+'.cs','Manifest/'+name+'.cs')
put('Manifest/Manifest.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
put('Manifest/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")
msbuild_library(name="Manifest",project="Manifest.csproj",target_framework="net10.0",srcs=glob(["*.cs"]),nullable="disable",linux_worker=True,visibility=["//visibility:public"])
''')
for name in ['OrchardCore.Module.Targets.props','OrchardCore.Module.Targets.targets']:
 copy('src/OrchardCore/OrchardCore.Module.Targets/'+name,'RazorModule/'+name)
copy('src/OrchardCore/OrchardCore.Application.Targets/OrchardCore.Application.Targets.targets','ModuleApp/OrchardCore.Application.Targets.targets')
put('RazorModule/RazorModule.csproj','''<Project Sdk="Microsoft.NET.Sdk.Razor"><Import Project="OrchardCore.Module.Targets.props" /><PropertyGroup><TargetFramework>net10.0</TargetFramework><AddRazorSupportForMvc>true</AddRazorSupportForMvc></PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" /><ProjectReference Include="../Manifest/Manifest.csproj" /></ItemGroup></Project>''')
put('RazorModule/Directory.Build.targets','<Project><Import Project="OrchardCore.Module.Targets.targets" /></Project>')
put('RazorModule/Marker.cs','public class RazorModuleMarker {}')
put('RazorModule/Views/Shared/Hello.cshtml','<p>hello razor</p>')
put('RazorModule/wwwroot/message.txt','module asset')
put('RazorModule/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_items")
msbuild_items(name="view_resource",item_type="EmbeddedResource",srcs=["Views/Shared/Hello.cshtml"],metadata={"Link":"Views/Shared/Hello.cshtml"})
msbuild_items(name="asset",item_type="EmbeddedResource",srcs=["wwwroot/message.txt"],metadata={"Link":"wwwroot/message.txt"})
msbuild_items(name="razor",item_type="RazorGenerate",srcs=["Views/Shared/Hello.cshtml"],metadata={"Link":"Views/Shared/Hello.cshtml"})
msbuild_library(name="RazorModule",project="RazorModule.csproj",target_framework="net10.0",srcs=["Marker.cs"],deps=["//Manifest"],items=[":view_resource",":asset",":razor"],msbuild_imports=["OrchardCore.Module.Targets.props","OrchardCore.Module.Targets.targets","Directory.Build.targets"],framework_refs=["Microsoft.AspNetCore.App"],export_targets={"GetModuleProjectName":[]},linux_worker=True,visibility=["//visibility:public"])
''')
put('ModuleApp/ModuleApp.csproj','''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" /><ProjectReference Include="../RazorModule/RazorModule.csproj" /></ItemGroup><Import Project="OrchardCore.Application.Targets.targets" /></Project>''')
program='''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using OrchardCore.Modules.Manifest;
using Microsoft.AspNetCore.Razor.Hosting;
using Microsoft.AspNetCore.Mvc.Razor;
using Microsoft.AspNetCore.Mvc.Rendering;
var names=Assembly.GetExecutingAssembly().GetCustomAttributes<ModuleNameAttribute>().Select(a=>a.Name).ToArray();
if(names.Length!=1 || names[0]!="RazorModule") throw new Exception("Missing module metadata");
var module=typeof(RazorModuleMarker).Assembly;
if(module.GetCustomAttribute<ModuleMarkerAttribute>()?.Id!="RazorModule") throw new Exception("Missing module marker");
using var resource=module.GetManifestResourceStream("RazorModule.wwwroot>message.txt")!;
using var reader=new StreamReader(resource);
var view=module.GetCustomAttributes<RazorCompiledItemAttribute>().Single(a=>a.Identifier=="/Views/Shared/Hello.cshtml");
var page=(RazorPage)Activator.CreateInstance(view.Type)!;
using var writer=new StringWriter();page.ViewContext=new ViewContext { Writer=writer };
await page.ExecuteAsync();
Console.WriteLine(names[0]+"|"+reader.ReadToEnd()+"|"+writer.ToString());
'''
put('ModuleApp/Code.cs',program)
put('ModuleApp/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_target_items")
msbuild_target_items(name="modules",deps=["//RazorModule"],target="GetModuleProjectName",item_type="ModuleProjectNames",before_targets=["ResolveModuleProjectReferences"])
msbuild_binary(name="ModuleApp",project="ModuleApp.csproj",target_framework="net10.0",srcs=["Code.cs"],deps=["//RazorModule"],items=[":modules"],msbuild_imports=["OrchardCore.Application.Targets.targets"],framework_refs=["Microsoft.AspNetCore.App"],linux_worker=True)
''')
expected='RazorModule|module asset|<p>hello razor</p>'
raw=folder/'raw-module'
if raw.exists(): shutil.rmtree(raw)
raw.mkdir()
for name in ['Manifest','RazorModule','ModuleApp']:
 shutil.copytree(workspace/name,raw/name,ignore=shutil.ignore_patterns('BUILD.bazel','bin','obj'))
p=subprocess.run([str(sdk/'dotnet'),'run','--project',str(raw/'ModuleApp'),'-c','Release','-p:NuGetAudit=false'],capture_output=True,text=True,timeout=240)
(folder/'module-raw.log').write_text(p.stdout+p.stderr)
assert p.returncode==0 and expected in p.stdout,p.stdout[-5000:]+p.stderr[-3000:]
print('raw-module',p.returncode,flush=True)
run_root=Path(tempfile.mkdtemp(prefix='module-run-',dir=folder))
base=run_root/'base';rows=[]
def run(case,expected=expected):
 p=subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//ModuleApp','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(run_root/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=workspace,capture_output=True,text=True,timeout=240)
 output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
 assert p.returncode==0 and p.stdout.strip()==expected,(case,output[-6500:])

 if case=='module-relocated-cache': assert '2 disk cache hit' in output,output[-1500:]
 rows.append(dict(case=case,exit=p.returncode));print(case,p.returncode,flush=True)
run('module-razor-assets')
put('RazorModule/wwwroot/message.txt','changed asset')
run('module-resource-edit',expected.replace('module asset','changed asset'))
put('RazorModule/Views/Shared/Hello.cshtml','<p>changed razor</p>')
changed=expected.replace('module asset','changed asset').replace('hello razor','changed razor')
run('module-razor-edit',changed)
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
# Delete the producer output tree before compiling a consumer at a new path.
shutil.rmtree(base)
relocated=run_root/'relocated';relocated.mkdir(exist_ok=True)
for name in ['Manifest','RazorModule','ModuleApp']:
 shutil.copytree(workspace/name,relocated/name,dirs_exist_ok=True)
for name in ['MODULE.bazel','MODULE.bazel.lock','BUILD.bazel']:
 if (workspace/name).exists():shutil.copyfile(workspace/name,relocated/name)
workspace=relocated;base=run_root/'recovered-base';put('ModuleApp/Code.cs','// Recompile at a new workspace path with cached module outputs.\n'+program)
run('module-relocated-cache',changed)
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
(folder/'module-report.json').write_text(json.dumps(rows,indent=2))
