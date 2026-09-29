"""Generic graph contract controls; all builds use disposable sources."""

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
DOTNET = SDK / 'dotnet'
RUNNER = ROOT / 'tools/GraphBuild/bin/Release/net10.0/GraphBuild.dll'
ENV = dict(os.environ, DOTNET_ROOT=str(SDK), DOTNET_CLI_TELEMETRY_OPTOUT='1')


def run(*args, success=True):
    result = subprocess.run([str(x) for x in args], env=ENV, text=True, capture_output=True)
    if (result.returncode == 0) != success:
        raise AssertionError(result.stdout + result.stderr)
    return result


def fixture(root, count=3):
    (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><LangVersion>latest</LangVersion></PropertyGroup></Project>')
    for index in range(count):
        directory = root / f'P{index}'
        directory.mkdir()
        reference = f'<ItemGroup><ProjectReference Include="../P{index-1}/P{index-1}.csproj" /></ItemGroup>' if index else ''
        (directory / f'P{index}.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
            + ('<OutputType>Exe</OutputType>' if index == count - 1 else '')
            + '</PropertyGroup>' + reference + '</Project>')
        (directory / 'Code.cs').write_text(f'System.Console.WriteLine(P{count - 2}.Value());' if index == count - 1 else
                                          f'public class P{index} {{ public static int Value() => ' + (f'P{index - 1}.Value(); }}' if index else '1; }'))
    run(DOTNET, 'restore', root / f'P{count - 1}/P{count - 1}.csproj', '--source', root, '-p:NuGetAudit=false')
    return {
        'Version': 1, 'Entry': f'P{count - 1}/P{count - 1}.csproj', 'SdkVersion': '10.0.400',
        'Properties': {'Configuration': 'Release'}, 'SharedInputs': ['Directory.Build.props'],
        'Projects': {f'P{i}/P{i}.csproj': {
            'Inputs': sorted(str(p.relative_to(root)) for p in (root / f'P{i}').rglob('*') if p.is_file()),
            'OutputDirectories': [f'P{i}/bin/Release/net10.0', f'P{i}/obj/Release/net10.0'],
        } for i in range(count)},
    }


def inspect(root, contract, success=True):
    manifest = root.parent / 'contract.json'
    report = root.parent / 'report.json'
    manifest.write_text(json.dumps(contract))
    result = run(DOTNET, RUNNER, 'inspect', root, manifest, report, success=success)
    if not success:
        return result.stderr
    return {node['project']: node['fingerprint'] for node in json.loads(report.read_text())}


def main():
    with tempfile.TemporaryDirectory(prefix='generic-graph-') as temporary:
        root = Path(temporary).resolve() / 'workspace'
        root.mkdir()
        contract = fixture(root)
        base = inspect(root, contract)
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        edited = inspect(root, contract)
        assert [p for p in base if base[p] != edited[p]] == ['P0/P0.csproj']
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><LangVersion>preview</LangVersion></PropertyGroup></Project>')
        imported = inspect(root, contract)
        assert all(imported[p] != edited[p] for p in edited)
        contract['SharedInputs'] = []
        assert 'Undeclared graph input' in inspect(root, contract, success=False)
        contract['SharedInputs'] = ['Directory.Build.props']
        contract['Projects']['P1/P1.csproj']['OutputDirectories'].append('P0/bin/Release/net10.0')
        assert 'Overlapping output' in inspect(root, contract, success=False)
        print('PASS: source/import invalidation, undeclared imports, output ownership')


if __name__ == '__main__':
    main()
