"""Qualify cold/reused Serilog preparation and producer-free native execution."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from preparation_reuse import prepared_view, ROOT
from discovery_contract import SDK
from probe_serilog_discovery import REVISION
from probe_bazel import json_stream


def probe(repository, packages, output, incremental=False):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    source.mkdir()
    archive = subprocess.check_output(['git', '-C', str(repository), 'archive', REVISION])
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(source, filter='data')
    for package in ('polysharp/1.15.0', 'microsoft.net.illink.tasks/10.0.11'):
        shutil.copytree(packages / package, source / '.nuget/packages' / package)
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'))
    report = dict(accepted=False, upstreamRevision=REVISION, cases={})
    from protected_store import ProtectedStore
    options = dict(incremental_sources=True, protected_store=ProtectedStore()) if incremental else {}

    def run(name, command, cwd):
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    try:
        run('restore', [SDK / 'dotnet', 'restore', source / 'src/Serilog/Serilog.csproj',
            '-p:TargetFramework=net10.0', '--packages', source / '.nuget/packages'], source)
        entries = [dict(project='src/Serilog/Serilog.csproj', globalProperties={'Configuration':'Release', 'TargetFramework':'net10.0'})]
        with prepared_view(source, output / 'cache', output / 'cold', entries, **options) as result:
            assert not result['reused'] and result['discoveryExecuted'], result
            report['cases']['cold'] = result
        if incremental:
            program = source / 'src/Serilog/Log.cs'
            original = program.read_text()
            marker = 'public static class Log\n{'
            assert original.count(marker) == 1
            program.write_text(original.replace(marker, marker +
                '\n    /// <summary>Native incremental preparation probe.</summary>\n'
                '    public static string IncrementalProbe => "incremental";\n'))
            with prepared_view(source, output / 'cache', output / 'edited', entries, **options) as result:
                assert result['reason'] == 'source-content-changed' and not result['discoveryExecuted'], result
                report['cases']['source-content'] = result
        relocated = output / 'relocated-source'
        shutil.copytree(source, relocated)
        for path in relocated.rglob('*'):
            if path.is_file() and 'obj' in path.relative_to(relocated).parts:
                path.write_bytes(path.read_bytes().replace(str(source).encode(), str(relocated).encode()))
        shutil.rmtree(source)
        shutil.rmtree(output / 'cold')
        recovered = output / 'recovered'
        with prepared_view(relocated, output / 'cache', recovered, entries, **options) as result:
            assert result['reused'] and not result['discoveryExecuted'], result
            shutil.rmtree(relocated)
            bazel = Path(os.environ.get('RULES_MSBUILD_BAZEL', ROOT / '.tools/bin/bazel'))
            execution = output / 'execution.json'
            run('build', [bazel, '--batch', '--nohome_rc', '--noworkspace_rc',
                '--output_base=' + str(output / 'bazel-base'), 'build', '//:all',
                '--disk_cache=' + str(output / 'empty-cache'), '--spawn_strategy=darwin-sandbox',
                '--strategy=MsbuildProject=darwin-sandbox', '--jobs=2', '--noshow_progress',
                '--execution_log_json_file=' + str(execution)], recovered)
            actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
            assert len(actions) == 1 and not actions[0].get('cacheHit') and actions[0]['runner'] == 'darwin-sandbox', actions
            graph = json.loads((recovered / 'graph.json').read_text())
            identity = graph['nodes'][0]['id']
            dll = recovered / f'bazel-bin/node_{identity}.bundle/artifacts/src/Serilog/bin/Release/net10.0/Serilog.dll'
            consumer = output / 'consumer'
            consumer.mkdir()
            shutil.copyfile(dll, consumer / 'Serilog.dll')
            (consumer / 'Consumer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="Serilog"><HintPath>Serilog.dll</HintPath></Reference></ItemGroup></Project>')
            (consumer / 'Program.cs').write_text('using var logger = new Serilog.LoggerConfiguration().CreateLogger(); logger.Information("Recovered"); System.Console.WriteLine(typeof(Serilog.Log).Assembly.GetName().Name);')
            if incremental:
                with (consumer / 'Program.cs').open('a') as stream:
                    stream.write('System.Console.WriteLine(Serilog.Log.IncrementalProbe);')
            run('consumer-build', [SDK / 'dotnet', 'build', '-c', 'Release', '--nologo'], consumer)
            actual = run('consumer-run', [SDK / 'dotnet', consumer / 'bin/Release/net10.0/Consumer.dll'], consumer)
            assert actual == ('Serilog\nincremental' if incremental else 'Serilog'), actual
            report['cases']['recovered-execution'] = dict(**result, nativeActions=1, consumerOutput=actual, producerAbsent=True)
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--incremental', action='store_true')
    args = parser.parse_args()
    print(json.dumps(probe(args.source, args.packages, args.output, args.incremental), indent=2))
