"""A declared native generator and its data survive graph sync and replay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from fixture_host import temporary_directory, bazel_environment, bazel_startup, sdk_declaration
from qualify import DOTNET, ROOT, RUNNER, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph-worker', action='store_true')
    options = parser.parse_args()
    with temporary_directory(prefix='graph-native-tools-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        (root / 'App').mkdir(parents=True)
        shutil.copy(ROOT / 'global.json', root / 'global.json')
        code = base / 'generator.c'
        executable_name = 'generator.exe' if os.name == 'nt' else 'generator'
        data_name = executable_name + '.data'
        def compile_tool(add):
            code.write_text('#include <stdio.h>\nint main(int argc,char **argv) { if(argc!=2)return 1; char path[4096]; '
                'snprintf(path,sizeof(path),"%s.data",argv[0]); FILE *in=fopen(path,"r"); if(!in)return 2; '
                'int value; if(fscanf(in,"%d",&value)!=1)return 3; fclose(in); FILE *out=fopen(argv[1],"w"); if(!out)return 4; '
                f'fprintf(out,"public class Generated {{ public static int Value => %d; }}",value+{add}); return fclose(out); }}')
            run(os.environ.get('CC', 'cc'), code, '-o', root / executable_name)
        compile_tool(0)
        (root / data_name).write_text('41')
        shell = '' if os.name == 'nt' else ' ToolPath="/bin"'
        project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>' \
            f'<Target Name="Generate" BeforeTargets="CoreCompile"><Exec{shell} Command="&quot;$(GeneratorPath)&quot; &quot;$(IntermediateOutputPath)Generated.cs&quot;" />' \
            '<ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs" /></ItemGroup></Target></Project>'
        (root / 'App/App.csproj').write_bytes(project.encode())
        (root / 'App/Program.cs').write_text('System.Console.WriteLine(Generated.Value);')
        (root / 'mapping.json').write_text(json.dumps({'projectDefaults': {'documents': {'App/App.csproj': {
            'sha256': hashlib.sha256(project.encode()).hexdigest(), 'targets': ['Generate'], 'tasks': [], 'inputs': []}}}}))
        (root / 'MODULE.bazel').write_text('module(name="graph_native_tools")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            + sdk_declaration(global_json='//:global.json') + 'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        authored = 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_native_tool","msbuild_file_binding","msbuild_graph_binary")\n' \
            'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n' \
            f'msbuild_layout(name="layout",paths={{"{executable_name}":"bin/{executable_name}","{data_name}":"bin/{data_name}"}})\n' \
            f'msbuild_native_tool(name="tool",layout=":layout",entry_point="bin/{executable_name}")\n' \
            'msbuild_file_binding(name="binding",tool=":tool",property_name="GeneratorPath")\n' \
            'msbuild_sync(name="sync",projects=["App/App.csproj"],bindings=[":binding"],mappings="mapping.json")\n'
        (root / 'BUILD.bazel').write_text(authored)
        prefix = bazel_startup(f'--output_base={base / "bazel"}')
        def bazel(*args):
            if options.graph_worker and args[0] in ('run', 'build'):
                args = args[:1] + ('--strategy=MSBuildGraph=worker', '--worker_sandboxing') + args[1:]
            result = subprocess.run(prefix + list(args), cwd=root, env=bazel_environment(), text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout + result.stderr
        try:
            bazel('run', '//:sync')
            graph_options = ',linux_stable_paths=True,linux_worker=True' if options.graph_worker else ''
            (root / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph"' + graph_options + ')\nmsbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
            assert '41' in bazel('run', '//:app').splitlines()
            replay = base / 'replay'
            output = subprocess.check_output(prefix + ['info', 'bazel-bin'], cwd=root, env=bazel_environment(), text=True)
            shutil.copytree(Path(output.strip()) / 'graph.graph/workspace', replay)
            # Include the root so Restore can create its temporary NuGet.Config;
            # Bazel makes outputs read-only. Preserve executable bits throughout.
            replay.chmod(replay.stat().st_mode | 0o200)
            for file in replay.rglob('*'):
                file.chmod(file.stat().st_mode | 0o200)
            def build(value, hits):
                for folder in ['bin', 'obj']:
                    shutil.rmtree(replay / 'App' / folder, ignore_errors=True)
                report = base / 'report.json'
                run(DOTNET, RUNNER, 'action', replay, root / 'graph.generated.json', report, base / 'cache')
                assert json.loads(report.read_text())['hits'] == hits, report.read_text()
                assert run(DOTNET, replay / 'App/bin/Release/net11.0/App.dll').stdout.strip() == str(value)
            build(41, 0)
            build(41, 1)
            (root / data_name).write_text('42')
            assert '42' in bazel('run', '//:app').splitlines()
            (replay / '.graph-tools/0/bin' / data_name).write_text('42')
            build(42, 0)
            compile_tool(1)
            assert '43' in bazel('run', '//:app').splitlines()
            shutil.copy(root / executable_name, replay / '.graph-tools/0/bin' / executable_name)
            build(43, 0)
            build(43, 1)
            executable = replay / '.graph-tools/0/bin' / executable_name
            if os.name == 'nt':
                executable.write_bytes(b'invalid Windows executable')
            else:
                mode = executable.stat().st_mode
                executable.chmod(mode & ~0o111)
            for folder in ['bin', 'obj']:
                shutil.rmtree(replay / 'App' / folder, ignore_errors=True)
            failed = run(DOTNET, RUNNER, 'action', replay, root / 'graph.generated.json', base / 'report.json', base / 'cache', success=False)
            message = failed.stdout + failed.stderr
            assert ('MSB3073' if os.name == 'nt' else 'Permission denied') in message, message
            shutil.copy2(root / executable_name, executable)
            build(43, 1)
            bazel('run', '//:sync', '--', '--check')
            print('PASS: native generator closure, executable mode, replay, data and binary invalidation')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
