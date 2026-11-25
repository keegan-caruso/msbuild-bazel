"""Bounded Blazor SSR + real server-circuit control on the graph/plugin backend.

Requires Release-built ProjectSync/GraphBuild, RULES_MSBUILD_DOTNET_ROOT,
and HTTPS access to acquire the pinned SDK 11 implicit static-asset package.
No browser or NuGet client package: the probe sends the minimal BlazorPack
StartCircuit invocation and observes CircuitHandler.OnCircuitOpenedAsync.
It does not claim browser event dispatch, DOM updates, or reconnect coverage.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request

from qualify import DOTNET, ENV, ROOT, RUNNER, SDK, run


def main():
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN',
                'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY']:
        ENV.pop(key, None)
    with tempfile.TemporaryDirectory(prefix='graph-blazor-') as temporary:
        base = Path(temporary)
        root = base / 'workspace'
        app = root / 'App'
        app.mkdir(parents=True)
        (app / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
        (app / '_Imports.razor').write_text('@using Microsoft.AspNetCore.Components.Web\n@using static Microsoft.AspNetCore.Components.Web.RenderMode\n')
        page = app / 'Page.razor'
        page.write_text('@page "/"\n@rendermode InteractiveServer\n<h1>blazor-v1</h1>\n<button @onclick="() => count++">Count: @count</button>\n@code { int count; }\n')
        shutil.copy(Path(__file__).with_name('BlazorProbe.cs.txt'), app / 'Program.cs')
        # SDK 11 implicitly references this framework static-asset pack for Razor
        # components. Acquire verified archive bytes before the offline action.
        packages = root / '.package-source'
        packages.mkdir()
        archive = packages / 'microsoft.aspnetcore.app.internal.assets.11.0.0.nupkg'
        url = 'https://api.nuget.org/v3-flatcontainer/microsoft.aspnetcore.app.internal.assets/11.0.0/' + archive.name
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        assert hashlib.sha256(data).hexdigest() == '1a918b5f5ed0122736b51f2357453f7d4b6ccaa75e8a7a8711a2919466c3e237'
        archive.write_bytes(data)
        package_view = base / 'package'
        package_view.mkdir()
        shutil.copy(archive, package_view / archive.name)
        inputs = base / 'inputs.json'
        inputs.write_text(json.dumps({'Inputs': [], 'Packages': [{'Id': 'Microsoft.AspNetCore.App.Internal.Assets',
            'Version': '11.0.0', 'Runfile': 'package'}], 'PackageLock': '//:packages'}))
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net11.0/ProjectSync.dll', root,
            SDK / 'sdk/11.0.100', 'App/App.csproj', '--inputs', inputs, '--runfiles', base, '--package-build')
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        def build(hits, marker):
            for name in ['bin', 'obj']:
                shutil.rmtree(app / name, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            result = json.loads(report.read_text())
            assert result['hits'] == hits and result['misses'] == 1 - hits, result
            output = run(DOTNET, app / 'bin/Release/net11.0/App.dll', marker).stdout
            assert 'PASS: SSR ' + marker + '; server circuit opened' in output, output
            print(f"{marker}: hits={result['hits']} misses={result['misses']}; SSR + server circuit", flush=True)
            return (app / 'bin/Release/net11.0/App.dll').read_bytes()
        original = build(0, 'blazor-v1')
        assert build(1, 'blazor-v1') == original
        page.write_text(page.read_text().replace('blazor-v1', 'blazor-v2'))
        assert build(0, 'blazor-v2') != original
        print('PASS: Blazor SSR, actual StartCircuit, snapshot replay, Razor edit invalidation')


if __name__ == '__main__':
    main()
