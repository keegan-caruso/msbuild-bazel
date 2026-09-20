"""Project-built generator execution, tool dependency loading and invalidation."""
import json
import os
from pathlib import Path
import subprocess
import sys

folder = Path(sys.argv[1]).resolve()
workspace = folder / 'src'
bazel = os.environ['RULES_MSBUILD_BAZEL']
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
def put(name, text):
    path = workspace / name
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(text)
def rule(kind, name, **extra):
    return 'load("@rules_msbuild//msbuild:defs.bzl","'+kind+'")\n'+kind+'('+','.join(k+'='+json.dumps(v) for k,v in dict(name=name,project=name+'.csproj',target_framework='net10.0',srcs=['Code.cs'],visibility=['//visibility:public'],**extra).items())+',linux_worker=True)\n'
put('ToolHelper/ToolHelper.csproj', project.format('', ''))
helper='public static class ToolHelper { public static string Text() => "public static class Made { public static int Value => 7; }"; }'
put('ToolHelper/Code.cs', helper)
put('ToolHelper/BUILD.bazel', rule('msbuild_library','ToolHelper'))
put('Generator/Generator.csproj',project.format('', '<ItemGroup><ProjectReference Include="../ToolHelper/ToolHelper.csproj" /><Reference Include="$(MSBuildBinPath)/Roslyn/bincore/Microsoft.CodeAnalysis.dll"><Private>false</Private></Reference></ItemGroup>'))
put('Generator/Code.cs', 'using Microsoft.CodeAnalysis; [Generator] public class Generator : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { c.AddSource("Made.g.cs", ToolHelper.Text()); } }')
put('Generator/BUILD.bazel', rule('msbuild_library','Generator',deps=['//ToolHelper']))
consumer=project.format('<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false" /></ItemGroup>')
put('GeneratedApp/GeneratedApp.csproj', consumer)
put('GeneratedApp/Code.cs', 'System.Console.WriteLine(Made.Value);')
put('GeneratedApp/BUILD.bazel', rule('msbuild_binary','GeneratedApp',analyzers=['//Generator']))
rows=[]
base=folder/'analyzer-base'
def run(case, expected='7', error=None):
    p=subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//GeneratedApp','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'analyzer-cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=workspace,capture_output=True,text=True,timeout=240)
    output=p.stdout+p.stderr
    (folder/(case+'.log')).write_text(output)
    assert (p.returncode==0 and p.stdout.strip()==expected) if error is None else (p.returncode!=0 and error in output),(case,output[-6000:])
    rows.append(dict(case=case,exit=p.returncode));print(case,p.returncode,flush=True)
run('generator-execution')
put('ToolHelper/Code.cs',helper.replace('=> 7;', '=> 8;'))
run('generator-tool-body-edit','8')
put('GeneratedApp/Code.cs','System.Console.WriteLine(ToolHelper.Text());')
run('generator-no-compile-leak',error='CS0103')
put('GeneratedApp/Code.cs','System.Console.WriteLine(Made.Value);')
put('GeneratedApp/GeneratedApp.csproj',consumer.replace('ReferenceOutputAssembly="false"','ReferenceOutputAssembly="true"'))
run('generator-role-mismatch',error='analyzer role disagrees')
put('GeneratedApp/GeneratedApp.csproj',consumer)
run('generator-recovery','8')
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
# A new output tree must consume a cached generator implementation and its helper.
base=folder/'analyzer-recovered-base'
put('GeneratedApp/Code.cs','// Force consumer execution with restored tool inputs.\nSystem.Console.WriteLine(Made.Value);')
run('generator-cached-tool','8')
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
(folder/'analyzer-report.json').write_text(json.dumps(rows,indent=2))
