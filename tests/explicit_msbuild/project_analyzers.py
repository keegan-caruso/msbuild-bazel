"""Project-built generator execution, tool dependency loading and invalidation."""
import json
import re
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
consumer=project.format('<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" SetConfiguration="Configuration=Release" SetTargetFramework="TargetFramework=net10.0" ReferenceOutputAssembly="false" /></ItemGroup>')
put('GeneratedApp/GeneratedApp.csproj', consumer)
put('GeneratedApp/Code.cs', 'System.Console.WriteLine(Made.Value);')
put('GeneratedApp/BUILD.bazel', rule('msbuild_binary','GeneratedApp',analyzers=['//Generator']))
rows=[]
base=folder/'analyzer-base'
def run(case, expected='7', error=None):
    p=subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//GeneratedApp','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'analyzer-cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--output_groups=+diagnostics'],cwd=workspace,capture_output=True,text=True,timeout=240)
    output=p.stdout+p.stderr
    (folder/(case+'.log')).write_text(output)
    assert (p.returncode==0 and p.stdout.strip()==expected) if error is None else (p.returncode!=0 and error in output),(case,output[-6000:])
    row=dict(case=case,exit=p.returncode)
    if error is None:
        log=(workspace/'bazel-bin/GeneratedApp/GeneratedApp.diagnostics/compiler.log').read_text()
        matches=re.findall(r'/analyzer:([^\s\"\']+/Generator\.dll)',log)
        assert matches, case
        row['analyzerPath']=matches[-1]
    rows.append(row);print(case,p.returncode,flush=True)
    return row
initial=run('generator-execution')
put('GeneratedApp/Code.cs','// Consumer-only edit.\nSystem.Console.WriteLine(Made.Value);')
consumer_edit=run('generator-consumer-body-edit')
assert consumer_edit['analyzerPath']==initial['analyzerPath'], 'Unchanged analyzer closure changed physical path'
put('GeneratedApp/Code.cs','System.Console.WriteLine(Made.Value);')
for name, before, after in [('configuration','Configuration=Release','Configuration=Debug'),('framework','TargetFramework=net10.0','TargetFramework=net9.0')]:
    put('GeneratedApp/GeneratedApp.csproj',consumer.replace(before,after))
    run('analyzer-'+name+'-mismatch',error='Configured ProjectReference disagrees')
put('GeneratedApp/GeneratedApp.csproj',consumer)
run('configured-analyzer-recovered')
put('ToolHelper/Code.cs',helper.replace('=> 7;', '=> 8;'))
changed=run('generator-tool-body-edit','8')
assert changed['analyzerPath']!=initial['analyzerPath'], 'Changed helper reused the old analyzer load group'
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
# AdditionalFiles are project-relative MSBuild items. The task/compiler must run
# with that project directory, including when it lives below the workspace root.
put('Generator/Code.cs', 'using Microsoft.CodeAnalysis; [Generator] public class Generator : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { c.AddSource("Made.g.cs", "public static class Made { public const int Value = " + c.AdditionalFiles[0].GetText(c.CancellationToken)!.ToString().Trim() + "; }"); } }')
put('GeneratedApp/GeneratedApp.csproj', consumer.replace('</ItemGroup>', '<AdditionalFiles Include="Value.txt" /></ItemGroup>'))
put('GeneratedApp/BUILD.bazel', 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_items")\nmsbuild_items(name="extra",item_type="AdditionalFiles",srcs=["Value.txt"])\n' + rule('msbuild_binary','GeneratedApp',analyzers=['//Generator'],items=[':extra']))
put('GeneratedApp/Value.txt','9')
run('relative-additional-file','9')
put('GeneratedApp/Value.txt','10')
additional_changed=run('additional-file-edit','10')
(folder/'analyzer-report.json').write_text(json.dumps(rows,indent=2))

# Keep the worker alive: the next request must remove this previous load group.
old_path=additional_changed['analyzerPath']
put('Generator/Code.cs', 'using Microsoft.CodeAnalysis; [Generator] public class Generator : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { if (System.IO.File.Exists('+json.dumps(old_path)+')) throw new System.Exception("Old analyzer group remains visible"); try { System.IO.Directory.CreateDirectory("/__rules_msbuild/in/analyzers/forbidden"); } catch (System.IO.IOException) { c.AddSource("Made.g.cs", ToolHelper.Text()); return; } catch (System.UnauthorizedAccessException) { c.AddSource("Made.g.cs", ToolHelper.Text()); return; } throw new System.Exception("Analyzer inputs are writable"); } }')
put('GeneratedApp/GeneratedApp.csproj',consumer)
put('GeneratedApp/BUILD.bazel',rule('msbuild_binary','GeneratedApp',analyzers=['//Generator']))
run('analyzer-group-read-only-and-no-stale-files','8')
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
(folder/'analyzer-report.json').write_text(json.dumps(rows,indent=2))
