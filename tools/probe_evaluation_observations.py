"""Measure public MSBuild filesystem-hook coverage before authorizing identity reuse."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
    workspace = output / 'workspace'
    (workspace / 'imports').mkdir(parents=True)
    (workspace / 'sources').mkdir()
    (workspace / '.nuget/packages').mkdir(parents=True)
    report = dict(accepted=False, reuseEnabled=False, sdkVersion='10.0.400', platform=platform.platform(), cases={})
    environment = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'), NUGET_HTTP_CACHE_PATH=str(output / 'http'), MSBUILDDISABLENODEREUSE='1')

    def run(name, args, cwd=ROOT):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=environment, capture_output=True, text=True, timeout=180)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode: raise RuntimeError(name + ': ' + result.stdout[-3000:] + result.stderr[-3000:])

    def evaluate(name, mode='recorded', project='App.proj', properties=None):
        request = output / (name + '-request.json')
        result = output / (name + '-result.json')
        request.write_text(json.dumps(dict(workspace=str(workspace), dotnetRoot=str(dotnet), sdkVersion='10.0.400',
            entryPoints=[dict(project=project, globalProperties=properties or {})], properties=['Value','Indirect','Timestamp'],
            items=['Compile'], mode=mode, output=str(result))))
        run(name, [dotnet / 'dotnet', ROOT / 'tools/EvaluationProbe/bin/Release/net10.0/EvaluationProbe.dll', '--request', request])
        return json.loads(result.read_text())['rounds']

    def same(name, project='App.proj', properties=None):
        plain = evaluate(name + '-plain', 'plain', project, properties)[0]
        recorded = evaluate(name, 'recorded', project, properties)[0]
        assert plain['nodes'] == recorded['nodes'], name
        report['cases'][name] = dict(parity=True, observations=len(recorded['observations']))
        return recorded

    def paths(data, operation):
        return {o['path'] for o in data['observations'] if o['operation'] == operation}

    try:
        run('build', [dotnet / 'dotnet', 'build', ROOT / 'tools/EvaluationProbe', '-c', 'Release', '--nologo'])
        project = '<Project><Import Project="imports/*.props"/><Import Project="optional.props" Condition="Exists(\'optional.props\')"/><ItemGroup><Compile Include="sources/**/*.cs"/></ItemGroup></Project>'
        (workspace / 'App.proj').write_text(project)
        (workspace / 'imports/a.props').write_text('<Project><Import Project="nested.props"/></Project>')
        (workspace / 'imports/nested.props').write_text('<Project><PropertyGroup><Value>one</Value></PropertyGroup></Project>')
        (workspace / 'sources/Code.cs').write_text('class Code {}')
        cold = same('cold')
        assert any(o['operation']=='exists' and o['path'].endswith('/optional.props') and o['result']=='false' for o in cold['observations'])
        assert not paths(cold, 'read'), 'reassess XML read coverage: public hook behavior changed'
        assert any(i['path'].endswith('/nested.props') for i in cold['nodes'][0]['imports'])
        (workspace / 'optional.props').write_text('<Project><PropertyGroup><Value>optional</Value></PropertyGroup></Project>')
        optional = same('optional-appears')
        assert any(o['operation']=='exists' and o['path'].endswith('/optional.props') and o['result']=='true' for o in optional['observations'])
        (workspace / 'optional.props').unlink()
        same('optional-removed')
        (workspace / 'imports/z.props').write_text('<Project><PropertyGroup><Value>wildcard</Value></PropertyGroup></Project>')
        wildcard = same('wildcard-added')
        assert any('z.props' in o['result'] for o in wildcard['observations'] if o['operation']=='files')
        (workspace / 'imports/z.props').unlink()
        same('wildcard-removed')
        (workspace / 'sources/nested').mkdir()
        (workspace / 'sources/nested/New.cs').write_text('class New {}')
        sources = same('source-and-directory-added')
        assert len(sources['nodes'][0]['items']['Compile']) == 2
        changed = same('global-property', properties={'Value':'global'})
        assert changed['nodes'][0]['values']['Value'] == 'global'
        warm = evaluate('warm', 'warm')
        assert warm[0]['nodes'] == warm[1]['nodes']
        assert len(warm[1]['observations']) < len(warm[0]['observations'])
        report['cases']['warm-cache-gap'] = dict(first=len(warm[0]['observations']), second=len(warm[1]['observations']), eligibility=False)
        (workspace / 'untracked.txt').write_text('indirect-one')
        (workspace / 'App.proj').write_text(project.replace('</Project>', '<PropertyGroup><Indirect>$([System.IO.File]::ReadAllText(\'$(MSBuildThisFileDirectory)untracked.txt\'))</Indirect></PropertyGroup></Project>'))
        indirect = same('property-function-bypass')
        assert indirect['nodes'][0]['values']['Indirect'] == 'indirect-one'
        assert not any(o['path'].endswith('/untracked.txt') for o in indirect['observations'])
        (workspace / 'untracked.txt').write_text('indirect-two')
        bypass = same('bypassed-file-changed')
        assert bypass['observations'] == indirect['observations']
        assert bypass['nodes'][0]['values']['Indirect'] != indirect['nodes'][0]['values']['Indirect']
        (workspace / 'App.proj').write_text(project.replace('</Project>', '<PropertyGroup><Timestamp>@(Compile->\'%(ModifiedTime)\')</Timestamp></PropertyGroup></Project>'))
        timestamp = same('item-timestamp-bypass')
        assert timestamp['nodes'][0]['values']['Timestamp']
        assert not any(o['operation']=='mtime' for o in timestamp['observations'])
        (workspace / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (workspace / 'Directory.Build.props').write_text('<Project/>')
        (workspace / 'Directory.Build.targets').write_text('<Project/>')
        run('restore', [dotnet / 'dotnet', 'restore', workspace / 'App.csproj', '--packages', workspace / '.nuget/packages'], workspace)
        sdk = same('sdk-and-nuget-wrappers', 'App.csproj')
        imports = [i['path'] for i in sdk['nodes'][0]['imports']]
        assert any(p.endswith('.nuget.g.props') for p in imports)
        assert any('/Sdks/' in p for p in imports)
        assert not paths(sdk, 'read')
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    probe(parser.parse_args().output)
