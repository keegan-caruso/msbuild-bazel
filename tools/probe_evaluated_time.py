"""Qualify graph-backed time diagnostics against actual SDK import selection."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

from msbuild_graph_diagnostics import scan_graph


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[1]
    dotnet = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', repo / '.tools/dotnet')).resolve()
    workspace = output / 'workspace'
    workspace.mkdir()
    (workspace / '.nuget/packages').mkdir(parents=True)
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'),
        NUGET_PACKAGES=str(workspace / '.nuget/packages'), NUGET_HTTP_CACHE_PATH=str(output / 'http'),
        MSBUILDDISABLENODEREUSE='1', DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    report = dict(accepted=False, scope='evaluated-import-diagnostics', reuseEnabled=False,
        platform=platform.platform(), sdkVersion='10.0.400', cases={})

    def run(name, args, cwd):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True, text=True, timeout=180)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' failed: ' + result.stdout[-2500:] + result.stderr[-2500:])

    def export(name, flavor='A'):
        request = output / (name + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace), dotnetRoot=str(dotnet),
            packageRoot=str(workspace / '.nuget/packages'), sdkVersion='10.0.400',
            entryPoints=[dict(project='App.csproj', globalProperties=dict(Configuration='Release', Flavor=flavor))],
            output=str(output / (name + '-graph.json')))))
        run(name + '-export', [dotnet / 'dotnet', repo / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], workspace)
        return request

    def observe(name, request, error=None):
        result = scan_graph(request)
        (output / (name + '-diagnostics.json')).write_text(json.dumps(result, indent=2) + '\n')
        if error:
            assert result['errors'] and error in result['errors'][0]['message'], result['errors']
        else:
            assert not result['errors'], result['errors']
            assert result['inventoryVerified'] and not result['reuseEnabled']
        item = dict(error=result['errors'], inventoryVerified=result['inventoryVerified'],
            xmlFiles=len(result['files']), workspaceFindings=[dict(rule=f['rule'], file=Path(f['file']).name,
            phase=f['phase'], configuredNodes=f['configuredNodes']) for f in result['findings'] if Path(f['file']).is_relative_to(workspace)])
        report['cases'][name] = item
        return result, item

    try:
        files = {
            'global.json': '{"sdk":{"version":"10.0.400","rollForward":"disable"}}',
            'Directory.Build.props': '<Project><PropertyGroup><Flavor Condition="\'$(Flavor)\' == \'\'">A</Flavor><VersionImport>$(MSBuildThisFileDirectory)$(Flavor).props</VersionImport></PropertyGroup><Import Project="$(VersionImport)" /></Project>',
            'Directory.Build.targets': '<Project><Import Project="optional.props" Condition="Exists(\'optional.props\')"/><Import Project="inactive.props" Condition="false"/></Project>',
            'App.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup></Project>',
            'Program.cs': 'class App { static System.DateTime RuntimeClock() => System.DateTime.Now; }',
            'A.props': '<Project><PropertyGroup><BuildClock>$([System.DateTime]::UtcNow)</BuildClock></PropertyGroup></Project>',
            'B.props': '<Project><Target Name="Observe"><Message Text="%(Compile.ModifiedTime)"/></Target></Project>',
            'inactive.props': '<Project><PropertyGroup><Clock>$([System.DateTime]::Today)</Clock></PropertyGroup></Project>'}
        for name, value in files.items():
            (workspace / name).write_text(value)
        run('exporter-build', [dotnet / 'dotnet', 'build', repo / 'tools/GraphExport', '-c', 'Release', '--nologo'], repo)
        run('restore', [dotnet / 'dotnet', 'restore', 'App.csproj', '--packages', workspace / '.nuget/packages'], workspace)
        baseline = export('selected-A')
        result, item = observe('selected-A', baseline)
        assert item['workspaceFindings'] == [dict(rule='wall-clock', file='A.props', phase='evaluation', configuredNodes=item['workspaceFindings'][0]['configuredNodes'])]
        assert any('/Sdks/' in path or '/sdk/' in path for path in result['files'])
        assert not any(Path(p).name in ('Program.cs', 'inactive.props', 'B.props') for p in result['files'])
        _, changed = observe('selected-B', export('selected-B', 'B'))
        assert [f['rule'] for f in changed['workspaceFindings']] == ['item-timestamp']
        assert changed['workspaceFindings'][0]['file'] == 'B.props'
        (workspace / 'optional.props').write_text('<Project><Target Name="Optional"><Message Text="%(Compile.CreatedTime)"/></Target></Project>')
        old, _ = observe('old-membership-not-eligible', baseline)
        assert not any(Path(p).name == 'optional.props' for p in old['files'])
        assert old['eligibility'] == 'not-established'
        fresh, _ = observe('new-optional-import', export('optional'))
        assert any(Path(p).name == 'optional.props' for p in fresh['files'])
        os.utime(workspace / 'A.props', (946684800, 946684800))
        touched, _ = observe('timestamp-only-not-eligible', baseline)
        assert touched['inventory'] == result['inventory'] and touched['eligibility'] == 'not-established'
        (workspace / 'A.props').write_text('<Project/>')
        observe('changed-import', baseline, 'stale graph XML input')
        (workspace / 'A.props').unlink()
        observe('missing-import', baseline, 'missing or escaping')
        assert not list(workspace.glob('bin/**/*.dll'))
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    probe(parser.parse_args().output)
