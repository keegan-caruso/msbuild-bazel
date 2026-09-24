"""Scalar target result handoff, invalidation and cache recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

folder=Path(sys.argv[1]).resolve(); workspace=folder/'src'; bazel=os.environ['RULES_MSBUILD_BAZEL']
def put(name,text):
 p=workspace/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
producer=project.format('', '<Target Name="GetLabel" Returns="@(Labels)"><ItemGroup><Labels Include="first"><Kind>module</Kind></Labels></ItemGroup></Target>')
put('Labels/Labels.csproj',producer);put('Labels/Code.cs','public class LabelType {}')
put('Labels/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")
msbuild_library(name="Labels",project="Labels.csproj",target_framework="net10.0",srcs=["Code.cs"],export_targets={"GetLabel":["Kind"]},linux_worker=True,visibility=["//visibility:public"])
''')
consumer=project.format('<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="../Labels/Labels.csproj" /></ItemGroup><Target Name="UseLabels" BeforeTargets="GetAssemblyAttributes"><ItemGroup><AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute"><_Parameter1>%(ImportedLabel.Kind)</_Parameter1><_Parameter2>%(ImportedLabel.Identity)</_Parameter2></AssemblyAttribute></ItemGroup></Target>')
put('LabelApp/LabelApp.csproj',consumer)
program='using System; using System.Reflection; var a=Assembly.GetExecutingAssembly().GetCustomAttribute<AssemblyMetadataAttribute>()!; if(a.Key!="module") throw new Exception("Missing target metadata"); Console.WriteLine(a.Value);'
put('LabelApp/Code.cs',program)
build='''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_target_items")
msbuild_target_items(name="labels",deps=["//Labels"],target="GetLabel",item_type="ImportedLabel",before_targets=["UseLabels"])
msbuild_binary(name="LabelApp",project="LabelApp.csproj",target_framework="net10.0",srcs=["Code.cs"],deps=["//Labels"],items=[":labels"],linux_worker=True)
'''
put('LabelApp/BUILD.bazel',build)
run_root=Path(tempfile.mkdtemp(prefix='target-run-',dir=folder))
base=run_root/'base';rows=[]
def run(case,expected='first',error=None):
 p=subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','run','//LabelApp','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(run_root/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=workspace,capture_output=True,text=True,timeout=240)
 output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
 assert (p.returncode==0 and p.stdout.strip()==expected) if error is None else (p.returncode!=0 and error in output),(case,output[-6000:])

 if case=='target-cached-producer': assert '1 disk cache hit' in output,output[-1500:]
 rows.append(dict(case=case,exit=p.returncode));print(case,p.returncode,flush=True)
run('target-handoff')
put('Labels/Labels.csproj',producer.replace('Include="first"','Include="second"'))
run('target-result-edit','second')
put('LabelApp/BUILD.bazel',build.replace('target="GetLabel"','target="Missing"'))
run('target-not-exported',error='target is not exported')
put('LabelApp/BUILD.bazel',build.replace('item_type="ImportedLabel"','item_type="Compile"'))
run('target-source-item-rejected',error='cannot replace dependency/source declarations')
put('LabelApp/BUILD.bazel',build)
put('Labels/Labels.csproj',producer.replace('Include="first"','Include="$(MSBuildProjectDirectory)"'))
run('target-path-rejected',error='must be scalar values')
put('Labels/Labels.csproj',producer.replace('Name="GetLabel"','Name="RemovedLabel"'))
run('target-missing-in-project',error='MSB4057')
put('Labels/Labels.csproj',producer)
run('target-recovery')
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
base=run_root/'recovered-base';put('LabelApp/Code.cs','// Recompile using cached target results.\n'+program)
run('target-cached-producer')
subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','shutdown'],cwd=workspace,check=True)
(folder/'target-report.json').write_text(json.dumps(rows,indent=2))
