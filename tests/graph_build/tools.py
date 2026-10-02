"""A bound task carries project, package and data dependencies into graph actions."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from qualify import DOTNET, ROOT, RUNNER, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-host", action="store_true", help="qualify graph out-of-process task execution")
    parser.add_argument("--graph-worker", action="store_true", help="qualify the Linux persistent cache broker")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='graph-tools-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        def put(path, text):
            file = root / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)
        package = base / 'package'
        package.mkdir()
        (package / 'Number.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Version>1.0.0</Version></PropertyGroup></Project>')
        (package / 'Code.cs').write_text('public static class Number { public static int Value => 40; }')
        run(DOTNET, 'pack', package / 'Number.csproj', '-o', root, '-p:UseSharedCompilation=false', '-p:NuGetAudit=false')
        archive = (root / 'Number.1.0.0.nupkg').read_bytes()
        shutil.copy(ROOT / 'global.json', root / 'global.json')
        put('MODULE.bazel', 'module(name="graph_tools")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
        put('Helper/Helper.csproj', project.format('', '<ItemGroup><PackageReference Include="Number" Version="1.0.0" /></ItemGroup>'))
        put('Helper/Code.cs', 'public static class Helper { public static int Value() => Number.Value; }')
        put('Tasks/Tasks.csproj', project.format('<CopyLocalLockFileAssemblies>true</CopyLocalLockFileAssemblies>', '<ItemGroup><ProjectReference Include="../Helper/Helper.csproj" /><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false" /><Content Include="../delta.txt" Link="delta.txt" CopyToOutputDirectory="PreserveNewest" /></ItemGroup>'))
        put('Tasks/Code.cs', '''using Microsoft.Build.Framework;
public class Generate : ITask {
 public IBuildEngine BuildEngine { get; set; } = null!;
 public ITaskHost HostObject { get; set; } = null!;
 [Required] public string OutputFile { get; set; } = null!;
 public bool Execute() { var directory=System.IO.Path.GetDirectoryName(typeof(Generate).Assembly.Location)!;
 var value=Helper.Value()+int.Parse(System.IO.File.ReadAllText(System.IO.Path.Combine(directory,"delta.txt")));
 System.IO.File.WriteAllText(OutputFile,"public class Generated { public static int Value => "+value+"; }"); return true; }
}''')
        put('delta.txt', '1')
        factory = 'TaskHostFactory' if args.task_host else 'AssemblyTaskFactory'
        app = project.format('<OutputType>Exe</OutputType>', f'<UsingTask TaskName="Generate" AssemblyFile="$(TaskLocation)" TaskFactory="{factory}" />'
            '<Target Name="GenerateCode" BeforeTargets="CoreCompile"><Generate OutputFile="$(IntermediateOutputPath)Generated.cs" />'
            '<ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs" /></ItemGroup></Target>')
        put('App/App.csproj', app)
        put('App/Program.cs', 'System.Console.WriteLine(Generated.Value);')
        put('mapping.json', json.dumps({'projectDefaults': {'documents': {'App/App.csproj': {
            'sha256': hashlib.sha256(app.encode()).hexdigest(), 'targets': ['GenerateCode'], 'tasks': ['Generate'], 'inputs': []}}}}))
        put('tool-contract.json', json.dumps(dict(Version=1, Entry='Tasks/Tasks.csproj', SdkVersion='10.0.400', Properties={'Configuration':'Release'}, SharedInputs=['global.json'], Projects={
            'Helper/Helper.csproj': dict(Inputs=['Helper/Helper.csproj','Helper/Code.cs'],OutputDirectories=['Helper/bin/Release/net10.0','Helper/obj/Release/net10.0']),
            'Tasks/Tasks.csproj': dict(Inputs=['Tasks/Tasks.csproj','Tasks/Code.cs','delta.txt'],OutputDirectories=['Tasks/bin/Release/net10.0','Tasks/obj/Release/net10.0'])})))
        authored = ('load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_layout","msbuild_graph_runner","msbuild_tool","msbuild_file_binding","msbuild_nuget_package","msbuild_graph_binary")\n'
            'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            f'msbuild_nuget_package(name="number",package_id="Number",version="1.0.0",archive="Number.1.0.0.nupkg",archive_sha256="{hashlib.sha256(archive).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(archive).digest()).decode()}")\n'
            'msbuild_graph_runner(name="tool_runner")\n'
            'msbuild_graph(name="tasks",runner=":tool_runner",contract="tool-contract.json",srcs=["global.json","Helper/Helper.csproj","Helper/Code.cs","Tasks/Tasks.csproj","Tasks/Code.cs","delta.txt"],packages=["Number.1.0.0.nupkg"],project_outputs={"Tasks/Tasks.csproj|net10.0":["Tasks/bin/Release/net10.0","Tasks.dll","Library"]})\n'
            'msbuild_graph_layout(name="task_layout",graph=":tasks",project="Tasks/Tasks.csproj")\n'
            'msbuild_tool(name="tool",layout=":task_layout",entry_point="Tasks.dll")\n'
            'msbuild_file_binding(name="binding",tool=":tool",property_name="TaskLocation")\n'
            'msbuild_sync(name="sync",projects=["App/App.csproj"],bindings=[":binding"],mappings="mapping.json")\n')
        if args.graph_worker:
            authored = authored.replace('name="tasks",runner=":tool_runner"', 'name="tasks",linux_stable_paths=True,linux_worker=True,runner=":tool_runner"')
        put('BUILD.bazel', authored)
        prefix = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={base / "bazel"}']
        worker_mode = args.graph_worker
        def bazel(*args, success=True):
            if worker_mode and args[0] in ("run", "build"):
                args = args[:1] + ("--strategy=MSBuildGraph=worker", "--worker_sandboxing", "--worker_max_instances=MSBuildGraph=1") + args[1:]
            result = subprocess.run(prefix + list(args), cwd=root, env=os.environ, text=True, capture_output=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result.stdout + result.stderr
        try:
            bazel('run', '//:sync')
            bazel('run', '//:sync', '--', '--check')
            contract = json.loads((root / 'graph.generated.json').read_text())
            assert contract['ToolProperties'] == {'TaskLocation': '.graph-tools/0/Tasks.dll'}
            graph_options = ',linux_stable_paths=True,linux_worker=True' if args.graph_worker else ''
            put('BUILD.bazel', authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\nmsbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
            assert '41' in bazel('run', '//:app').splitlines()
            replay = base / 'replay'
            shutil.copytree(root / 'bazel-bin/graph.graph/workspace', replay)
            for file in replay.rglob('*'):
                file.chmod(0o755 if file.is_dir() else 0o644)
            def replay_build(value, hits):
                for name in ['bin', 'obj']:
                    shutil.rmtree(replay / 'App' / name, ignore_errors=True)
                report = base / 'report.json'
                run(DOTNET, RUNNER, 'action', replay, root / 'graph.generated.json', report, base / 'snapshots')
                assert json.loads(report.read_text())['hits'] == hits
                assert run(DOTNET, replay / 'App/bin/Release/net10.0/App.dll').stdout.strip() == str(value)
            replay_build(41, 0)
            replay_build(41, 1)
            put('Helper/Code.cs', 'public static class Helper { public static int Value() => Number.Value+1; }')
            assert '42' in bazel('run', '//:app').splitlines()
            shutil.copy(root / 'bazel-bin/graph.graph/workspace/.graph-tools/0/Helper.dll', replay / '.graph-tools/0/Helper.dll')
            replay_build(42, 0)
            replay_build(42, 1)
            put('delta.txt', '2')
            data_result = bazel('run', '//:app')
            assert '43' in data_result.splitlines(), data_result + '\n' + (root / 'bazel-bin/graph.graph/report.json').read_text() + '\ndata=' + (root / 'bazel-bin/graph.graph/workspace/.graph-tools/0/delta.txt').read_text()
            (replay / '.graph-tools/0/delta.txt').write_text('2')
            replay_build(43, 0)
            bazel('run', '//:sync', '--', '--check')
            runtime = root / 'bazel-bin/graph.graph/workspace/.graph-tools/0'
            assert all((runtime / name).is_file() for name in ['Tasks.dll', 'Helper.dll', 'Number.dll', 'delta.txt'])
            current_build = (root / 'BUILD.bazel').read_text()
            put('BUILD.bazel', current_build.replace('property_name="TaskLocation"', 'property_name="ChangedLocation"'))
            assert 'Graph tool bindings changed' in bazel('run', '//:app', success=False)
            put('BUILD.bazel', current_build)
            print('PASS: bound task project/package/data closure and implementation/data edits without resync')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
