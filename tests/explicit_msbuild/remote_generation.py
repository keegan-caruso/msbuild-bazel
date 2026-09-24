"""Standalone remote generation: declared tools, input invalidation and recovery."""
import argparse
import hashlib
from pathlib import Path
from remote_support import RemoteFixture

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path);p.add_argument('--executor',required=True)
p.add_argument('--recover-workspace',type=Path)
a=p.parse_args();f=RemoteFixture(a.output,a.executor,a.recover_workspace);f.sdk()
if a.recover_workspace:
    try:
        actions=f.run('independent-recovery',['//:test'],[],tests=[])
        assert actions and all(x.get('cacheHit') for x in actions),actions
        assert any(x['mnemonic']=='MSBuildGenerate' for x in actions)
        assert hashlib.sha256((f.workspace/'bazel-bin/generate.generated/Generated.cs').read_bytes()).hexdigest()==(f.workspace/'expected.sha256').read_text()
    finally:f.shutdown()
    raise SystemExit()
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
f.put('Tasks.csproj',project.format('<ItemGroup><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false" /></ItemGroup>'))
f.put('Tasks.cs','''using Microsoft.Build.Framework;
public class Generate : ITask {
 public IBuildEngine BuildEngine { get; set; } = null!;
 public ITaskHost HostObject { get; set; } = null!;
 [Required] public string OutputFile { get; set; } = null!;
 [Required] public string InputFile { get; set; } = null!;
 public bool Execute() { var value=int.Parse(System.IO.File.ReadAllText(InputFile)); System.IO.File.WriteAllText(OutputFile,"public static class Generated { public static int Value() => "+(value+1)+"; }"); return true; }
}''')
f.put('Generate.csproj',project.format('<PropertyGroup><TaskLocation>/missing/Tasks.dll</TaskLocation></PropertyGroup><ItemGroup><ProjectReference Include="Tasks.csproj" ReferenceOutputAssembly="false" /></ItemGroup><UsingTask TaskName="Generate" AssemblyFile="$(TaskLocation)"/><Target Name="GenerateSource"><Generate InputFile="@(GeneratorInput)" OutputFile="$(GeneratedFile)" /></Target>'))
f.put('Test.csproj',project.format(''))
f.put('Test.cs','return Generated.Value()==3 ? 0 : 1;')
f.put('input.txt','2')
build='''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_tool","msbuild_file_binding","msbuild_items","msbuild_generate","msbuild_test")
msbuild_library(name="Tasks",project="Tasks.csproj",srcs=["Tasks.cs"],target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
msbuild_tool(name="tool",assembly=":Tasks")
msbuild_file_binding(name="binding",tool=":tool",property_name="TaskLocation")
msbuild_items(name="input",item_type="GeneratorInput",srcs=["input.txt"])
msbuild_generate(name="generate",project="Generate.csproj",target_framework="net10.0",tools=[":tool"],bindings=[":binding"],items=[":input"],targets=["GenerateSource"],outputs=["Generated.cs"],output_properties={"GeneratedFile":"Generated.cs"},linux_worker=True,allow_remote_execution=True)
msbuild_test(name="test",project="Test.csproj",srcs=["Test.cs",":generate"],target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
'''
f.put('BUILD.bazel',build)
assembly=lambda target:('MSBuildAssembly','//:'+target)
generate=('MSBuildGenerate','//:generate')
try:
    f.run('cold',['//:test'],[assembly('Tasks'),generate,assembly('test')],cold=True,tests=['//:test'])
    f.run('noop',['//:test'],[],tests=[])
    f.put('Test.cs','// unrelated consumer edit\nreturn Generated.Value()==3 ? 0 : 1;')
    f.run('consumer-edit',['//:test'],[assembly('test')],tests=['//:test'])
    f.put('input.txt','3');f.put('Test.cs','return Generated.Value()==4 ? 0 : 1;')
    f.run('input-edit',['//:test'],[generate,assembly('test')],tests=['//:test'])
    f.put('Tasks.cs',(f.workspace/'Tasks.cs').read_text().replace('value+1','value+2'))
    f.put('Test.cs','return Generated.Value()==5 ? 0 : 1;')
    f.run('tool-edit',['//:test'],[assembly('Tasks'),generate,assembly('test')],tests=['//:test'])
    f.put('BUILD.bazel',build.replace('items=[":input"]','items=[]'))
    f.run('missing-input',['//:test'],[generate],error='InputFile',tests=[])
    f.put('BUILD.bazel',build)
    f.run('restored',['//:test'],[],tests=[])
    digest=hashlib.sha256((f.workspace/'bazel-bin/generate.generated/Generated.cs').read_bytes()).hexdigest()
    f.put('expected.sha256',digest)
finally:f.shutdown()
