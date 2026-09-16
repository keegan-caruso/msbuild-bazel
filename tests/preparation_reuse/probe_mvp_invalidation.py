"""Native MVP source/import/fallback invalidation with executable work-set oracles."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from preparation_reuse import prepared_view, ROOT
from discovery_contract import SDK
from probe_bazel import json_stream


def probe(output, incremental=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, state = output / 'source', output / 'state'
    (source / 'App').mkdir(parents=True)
    (source / 'Shared').mkdir()
    (source / '.nuget/packages').mkdir(parents=True)
    props = source / 'Directory.Build.props'
    props.write_text('<Project><Import Project="optional.props" Condition="Exists(\'optional.props\')"/></Project>')
    (source / 'Directory.Build.targets').write_text('<Project/>')
    app = source / 'App/App.csproj'
    original = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>'
    app.write_text(original)
    (source / 'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    (source / 'Shared/Value.cs').write_text('public class Value { public static string Text => "mvp"; }')
    (source / 'App/Program.cs').write_text('System.Console.WriteLine(Value.Text + (System.Type.GetType("Added") is null ? ":base" : ":added"));\n#if OPTIONAL\nSystem.Console.WriteLine("optional");\n#endif\n')
    entries = [dict(project='App/App.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})]
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'))
    report = dict(accepted=False, cases={})
    from protected_store import ProtectedStore
    options = dict(incremental_sources=True, protected_store=ProtectedStore()) if incremental else {}
    bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT / '.tools/bin/bazel'))

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(name, command, cwd):
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=300)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ': ' + result.stdout[-3000:] + result.stderr[-3000:])
        return result.stdout.strip()

    def case(name, expected_reuse, expected_output, expected_projects, fresh_cache=False):
        consumer = output / name
        with prepared_view(source, state, consumer, entries, **options) as result:
            assert result['reused'] == expected_reuse, result
            if incremental:
                content_update = name in ('source-content', 'source-content-restored')
                assert result['discoveryExecuted'] == (not expected_reuse and not content_update), result
                if content_update: assert result['reason'] == 'source-content-changed', result
            graph = json.loads((consumer / 'graph.json').read_text())
            execution = output / (name + '-execution.json')
            cache = output / (name + '-empty-cache' if fresh_cache else 'disk-cache')
            run(name + '-build', [bazel, '--batch', '--nohome_rc', '--noworkspace_rc',
                '--output_base=' + str(output / (name + '-base')), 'build', '//:all',
                '--disk_cache=' + str(cache), '--spawn_strategy=darwin-sandbox',
                '--strategy=MsbuildProject=darwin-sandbox', '--jobs=2', '--noshow_progress',
                '--execution_log_json_file=' + str(execution)], consumer)
            nodes = {n['id']: n['project'].removeprefix('workspace/') for n in graph['nodes']}
            actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
            actual_projects = sorted(nodes[r['targetLabel'].split(':node_')[-1]] for r in actions if not r.get('cacheHit'))
            assert actual_projects == sorted(expected_projects), (name, actual_projects, expected_projects)
            assert all(r.get('cacheHit') or r.get('runner') == 'darwin-sandbox' for r in actions)
            identity = next(i for i, p in nodes.items() if p == 'App/App.csproj')
            actual = run(name + '-app', [SDK / 'dotnet', consumer / f'bazel-bin/node_{identity}.bundle/artifacts/App/bin/Release/net10.0/App.dll'], consumer)
            assert actual == expected_output, (name, actual, expected_output)
            report['cases'][name] = dict(preparation=result, expectedProjects=expected_projects,
                executedProjects=actual_projects, output=actual, actionCount=len(actions))
        save()

    try:
        run('restore', [SDK / 'dotnet', 'restore', app, '--packages', source / '.nuget/packages'], source)
        both = ['App/App.csproj', 'Shared/Shared.csproj']
        case('cold', False, 'mvp:base', both)
        case('unchanged', True, 'mvp:base', [])
        if incremental:
            program = source / 'App/Program.cs'
            previous = program.read_bytes()
            program.write_bytes(previous + b'\n// compile content delta\n')
            case('source-content', False, 'mvp:base', ['App/App.csproj'])
            program.write_bytes(previous)
            case('source-content-restored', False, 'mvp:base', [])
        added = source / 'App/Added.cs'
        added.write_text('public class Added {}')
        case('source-added', False, 'mvp:added', ['App/App.csproj'])
        added.unlink()
        case('source-removed', False, 'mvp:base', [])
        optional = source / 'optional.props'
        optional.write_text('<Project><PropertyGroup><DefineConstants>OPTIONAL</DefineConstants></PropertyGroup></Project>')
        case('optional-import-added', False, 'mvp:base\noptional', both)
        optional.unlink()
        case('optional-import-removed', False, 'mvp:base', [])
        # Metadata is outside reusable XML eligibility; fresh execution must
        # retain the requested edge and must not consume a stale generation.
        app.write_text(original.replace('Include="../Shared/Shared.csproj"/>',
            'Include="../Shared/Shared.csproj"><AdditionalProperties>Configuration=Release</AdditionalProperties></ProjectReference>'))
        case('reference-metadata-fresh', False, 'mvp:base', both, fresh_cache=True)
        app.write_text(original)
        # Debug is not a supported materialization configuration. Preserve the
        # existing generation and reject the request instead of serving Release.
        pointer = (state / 'current.json').read_bytes()
        entries[0]['globalProperties']['Configuration'] = 'Debug'
        try:
            with prepared_view(source, state, output / 'debug', entries):
                raise AssertionError('unsupported configuration returned a consumer')
        except ValueError as error:
            assert 'unsupported graph execution configuration' in str(error), str(error)
            report['cases']['configuration-rejected'] = dict(diagnostic=str(error), noStaleReuse=True)
        assert (state / 'current.json').read_bytes() == pointer
        report['accepted'] = True
    finally:
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--incremental', action='store_true')
    args = parser.parse_args()
    probe(args.output, args.incremental)
