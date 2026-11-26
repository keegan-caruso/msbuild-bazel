"""Runfiles parser and real ProjectSync / test-protocol consumer controls."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
DOTNET = SDK / ('dotnet.exe' if os.name == 'nt' else 'dotnet')


def run(*arguments):
    result = subprocess.run([str(value) for value in arguments], text=True, capture_output=True,
                            env=dict(os.environ, DOTNET_ROOT=str(SDK)))
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def main():
    with tempfile.TemporaryDirectory(prefix='runfiles-controls-') as temporary:
        base = Path(temporary).resolve()
        probe = base / 'probe'
        probe.mkdir()
        (probe / 'Program.cs').write_text((ROOT / 'tests/graph_build/Runfiles.cs.txt').read_text())
        sources = ''.join(f'<Compile Include="{escape(str(ROOT / "tools" / name))}" />' for name in ['Runfiles.cs', 'RelativePathComponents.cs'])
        (probe / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup>' + sources + '</ItemGroup></Project>')
        run(DOTNET, 'build', probe / 'Probe.csproj', '-c', 'Release', '-warnaserror', '--disable-build-servers', '-p:NuGetAudit=false')
        print(run(DOTNET, probe / 'bin/Release/net11.0/Probe.dll', base / 'parser').stdout.strip())

        # The real sync consumer must resolve a declared producer from either form.
        workspace = base / 'workspace'
        workspace.mkdir()
        (workspace / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
        tree = base / 'runfiles tree'
        (tree / 'repo').mkdir(parents=True)
        (tree / 'repo/produced.cs').write_text('public class Produced {}')
        (tree / 'repo/closures').mkdir()
        (tree / 'repo/closures/Task.dll').write_bytes(b'inert evaluation binding')
        inputs = base / 'inputs.json'
        inputs.write_text(json.dumps({'inputs': [{'path': 'generated/Produced.cs', 'label': '//:producer', 'runfile': 'repo/produced.cs'}], 'packages': [], 'packageLock': None, 'bindings': [{'label': '//:tool', 'property': 'DeclaredTool', 'runfiles': ['repo/closures'], 'entry': 'Task.dll', 'closure': True}]}))
        manifest = base / 'MANIFEST'
        manifest.write_text(f'repo/produced.cs {tree / "repo/produced.cs"}\nrepo/closures {tree / "repo/closures"}\n')
        sync = ROOT / 'tools/ProjectSync/bin/Release/net11.0/ProjectSync.dll'
        for location in [tree, manifest]:
            run(DOTNET, sync, workspace, SDK / 'sdk/11.0.100', 'App.csproj', '--inputs', inputs, '--runfiles', location)
            contract = json.loads((workspace / 'graph.generated.json').read_text())
            assert 'generated/Produced.cs' in contract['Projects']['App.csproj']['Configurations'][0]['Inputs'], contract
            assert contract['ToolProperties']['DeclaredTool'] == '.graph-tools/0/Task.dll', contract
        print('PASS: real ProjectSync producer lookup through directory and manifest')

        # A tiny reporting executable checks the adapter's resolved runner,
        # settings, data and adapter paths; it does not substitute for real MTP/VSTest.
        host = base / 'host'
        host.mkdir()
        (host / 'Host.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
        (host / 'Program.cs').write_text('''
using System.Text.Json;
if (File.ReadAllText("input.txt") != "declared data") return 7;
var output = args.Contains("--results-directory") ? args[Array.IndexOf(args, "--results-directory") + 1] : args.Single(a => a.StartsWith("/ResultsDirectory:"))[18..];
var settings = args.Contains("--config-file") ? args[Array.IndexOf(args, "--config-file") + 1] : args.Single(a => a.StartsWith("/Settings:"))[10..];
if (File.ReadAllText(settings) != "declared settings") return 8;
if (args.Any(a => a.StartsWith("/TestAdapterPath:")) && File.ReadAllText("adapter.txt") != "declared adapter") return 9;
Directory.CreateDirectory(output);
File.WriteAllText(Path.Combine(output, "results.trx"), "<TestRun xmlns='http://microsoft.com/schemas/VisualStudio/TeamTest/2010'><Results><UnitTestResult testName='Runfiles' outcome='Passed'/></Results><ResultSummary outcome='Completed'><Counters total='1'/></ResultSummary></TestRun>");
File.WriteAllText(Environment.GetEnvironmentVariable("ARGUMENT_RECEIPT")!, JsonSerializer.Serialize(args));
return 0;
''')
        run(DOTNET, 'build', host / 'Host.csproj', '-c', 'Release', '-warnaserror', '--disable-build-servers', '-p:NuGetAudit=false')
        payload = host / 'bin/Release/net11.0'
        adapter = tree / 'repo/adapter'
        adapter.mkdir()
        (adapter / 'adapter.txt').write_text('declared adapter')
        (tree / 'repo/settings.txt').write_text('declared settings')
        (tree / 'repo/input.txt').write_text('declared data')
        manifest.write_text(f'repo {tree / "repo"}\nrepo/runtime {payload}\nrepo/host {SDK}\nrepo/runner.dll {payload / "Host.dll"}\n')
        # Use a common physical ancestor for directory mode, avoiding SDK copies
        # or additional symlink privileges in this test fixture.
        directory_root = Path(os.path.commonpath([SDK, tree, payload]))
        artifact = ROOT / 'tools/ArtifactTools/bin/Release/net11.0/ArtifactTools.dll'
        for index, location in enumerate([directory_root, manifest]):
            for protocol in ['mtp', 'vstest']:
                receipt = base / f'{index}-{protocol}-arguments.json'
                request = {'entry': 'repo/runtime', 'assembly': 'Host', 'data': [{'source': 'repo/input.txt', 'path': 'input.txt'}], 'runtimeHost': {'directory': 'repo/host', 'entryPoint': DOTNET.name, 'launchMode': 'dotnet'}, 'testOptions': {'protocol': protocol, 'settings': 'repo/settings.txt', 'runner': 'repo/runner.dll', 'adapters': ['repo/adapter']}}
                if location == directory_root:
                    logical = lambda path: path.relative_to(directory_root).as_posix()
                    request['entry'] = logical(payload)
                    request['data'][0]['source'] = logical(tree / 'repo/input.txt')
                    request['runtimeHost']['directory'] = logical(SDK)
                    request['testOptions'].update(settings=logical(tree / 'repo/settings.txt'), runner=logical(payload / 'Host.dll'), adapters=[logical(adapter)])
                request_file = base / 'request.json'
                request_file.write_text(json.dumps(request))
                previous = dict(os.environ)
                try:
                    os.environ.update(RULES_MSBUILD_RUNFILES=str(location), ARGUMENT_RECEIPT=str(receipt), TEST_UNDECLARED_OUTPUTS_DIR=str(base / f'{index}-{protocol}-results'))
                    run(DOTNET, artifact, 'test-protocol', request_file)
                finally:
                    os.environ.clear()
                    os.environ.update(previous)
                assert receipt.is_file()
        print('PASS: real ArtifactTools directory/manifest runtime, data, settings, runner and adapter resolution')


if __name__ == '__main__':
    main()
