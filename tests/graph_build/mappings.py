"""Reviewed custom tasks consume generated Bazel inputs through graph sync."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from qualify import DOTNET, ROOT, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-mappings-') as temporary:
        root = Path(temporary).resolve()
        workspace = root / 'workspace'
        workspace.mkdir()
        tool = root / 'task'
        tool.mkdir()
        (tool / 'Task.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup>' + ''.join(
            f'<Reference Include="{name}" HintPath="{SDK}/sdk/10.0.400/{name}.dll" Private="false" />'
            for name in ['Microsoft.Build.Framework', 'Microsoft.Build.Utilities.Core']) + '</ItemGroup></Project>')
        (tool / 'Code.cs').write_text('public sealed class Generate : Microsoft.Build.Utilities.Task { '
            '[Microsoft.Build.Framework.Required] public string Input {get;set;} '
            '[Microsoft.Build.Framework.Required] public string Output {get;set;} '
            'public override bool Execute() { System.IO.File.WriteAllText(Output, '
            '"public class Generated { public static int Value => " + System.IO.File.ReadAllText(Input).Trim() + "; }"); return true; }}')
        run(DOTNET, 'build', tool / 'Task.csproj', '-c', 'Release', '--nologo')
        shutil.copy(tool / 'bin/Release/net10.0/Task.dll', workspace / 'Task.dll')
        shutil.copy(ROOT / 'global.json', workspace / 'global.json')
        (workspace / 'App').mkdir()
        project = workspace / 'App/App.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>'
            '<ItemGroup><Schema Include="../value.txt"><Mode>read</Mode></Schema></ItemGroup>'
            '<PropertyGroup><DefineConstants Condition="&apos;$(GraphProbe)&apos; == &apos;true&apos;">$(DefineConstants);GRAPH_PROBE</DefineConstants></PropertyGroup>'
            '<Target Name="RequireProbe" BeforeTargets="Restore"><Error Condition="&apos;$(GraphProbe)&apos; != &apos;true&apos;" Text="missing graph property" /></Target>'
            '<UsingTask TaskName="Generate" AssemblyFile="../tools/Task.dll" />'
            '<Target Name="GenerateCode" BeforeTargets="CoreCompile"><Generate Input="../value.txt" Output="$(IntermediateOutputPath)Generated.cs" />'
            '<ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs" /></ItemGroup></Target></Project>')
        (workspace / 'App/Program.cs').write_text('#if GRAPH_PROBE\nSystem.Console.WriteLine(Generated.Value);\n#else\n#error Missing graph property\n#endif')
        (workspace / 'value.txt').write_text('41')
        mapping = {'projectDefaults': {'properties': {'GraphProbe': 'true'}, 'inputItems': {'Schema': ['Mode']}, 'documents': {'App/App.csproj': {
            'sha256': hashlib.sha256(project.read_bytes()).hexdigest(), 'targets': ['GenerateCode', 'RequireProbe'],
            'tasks': ['Generate'], 'inputs': ['tools/Task.dll']}}}}
        (workspace / 'mappings.json').write_text(json.dumps(mapping))
        (workspace / 'MODULE.bazel').write_text('module(name="graph_mappings")\n'
            'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        authored = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            'genrule(name="task",srcs=["Task.dll"],outs=["generated/Task.dll"],cmd="cp $(location Task.dll) $@")\n'
            'msbuild_sync(name="sync",package_build=True,projects=["App/App.csproj"],mappings="mappings.json",inputs={":task":"tools/Task.dll"})\n')
        (workspace / 'BUILD.bazel').write_text(authored)
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={root / "bazel"}']
        def bazel(*arguments, success=True):
            result = subprocess.run(command + list(arguments), cwd=workspace, env=os.environ, text=True, capture_output=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result.stdout + result.stderr
        try:
            bazel('run', '//:sync')
            bazel('run', '//:sync', '--', '--check')
            (workspace / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\n'
                'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")\n'
                'app_graph(name="graph")\nmsbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
            assert '\n41\n' in bazel('run', '//:app')
            (workspace / 'value.txt').write_text('42')
            assert '\n42\n' in bazel('run', '//:app')
            project.write_text(project.read_text().replace('GenerateCode', 'ChangedCode'))
            assert 'Graph definition changed' in bazel('build', '//:graph', success=False)
            assert 'Custom document contract changed' in bazel('run', '//:sync', success=False)
            mapping['projectDefaults']['tools'] = [':task']
            (workspace / 'mappings.json').write_text(json.dumps(mapping))
            assert 'contract transfer for: tools' in bazel('run', '//:sync', success=False)
            del mapping['projectDefaults']['tools']
            mapping['projectDefaults']['properties']['RestoreSources'] = 'https://invalid.example'
            (workspace / 'mappings.json').write_text(json.dumps(mapping))
            assert 'Restore sources are controlled' in bazel('run', '//:sync', success=False)
            print('PASS: generated task assembly, declared task read, edited input, stale document and unsupported mapping rejection')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
