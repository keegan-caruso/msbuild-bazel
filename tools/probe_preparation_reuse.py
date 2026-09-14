"""Native RUL-6 acceptance: reuse, corruption recovery and recovered execution."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import preparation_reuse as reuse
from discovery_contract import SDK
from probe_bazel import json_stream


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source, state = output / 'source', output / 'cache'
    (source / 'App').mkdir(parents=True)
    (source / 'Shared').mkdir()
    (source / 'Directory.Build.props').write_text('<Project/>')
    (source / 'Directory.Build.targets').write_text('<Project/>')
    (source / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>')
    (source / 'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
    (source / 'Shared/Value.cs').write_text('public class Value { public static string Text => "recovered-rul6"; }')
    (source / 'App/Program.cs').write_text('System.Console.WriteLine(Value.Text);')
    entries = [dict(project='App/App.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})]
    report = dict(accepted=False, cases={})
    env = dict(os.environ, DOTNET_CLI_HOME=str(output / 'home'))

    def run(name, command, cwd=source):
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
        (output / (name + '.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    def record(name, reused, mutate=None):
        target = output / name
        if mutate: mutate()
        with reuse.prepared_view(source, state, target, entries) as result:
            assert result['reused'] == reused, result
            assert result['discoveryExecuted'] == (not reused), result
            report['cases'][name] = result
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        return target

    try:
        run('restore', [SDK / 'dotnet', 'restore', source / 'App/App.csproj', '--packages', source / '.nuget/packages'])
        cold = record('cold', False)
        baseline = reuse.payload_identity(cold)
        # A hit cannot secretly invoke the materializer or any discovery process.
        original_run = subprocess.run
        def no_discovery(command, *args, **kwargs):
            assert not any(str(x).endswith(('GraphExport.dll', 'EvaluationProbe.dll')) for x in command), command
            return original_run(command, *args, **kwargs)
        with patch.object(reuse.prepare_graph, '_prepare', side_effect=AssertionError('materializer ran on a hit')), patch('subprocess.run', side_effect=no_discovery):
            warm = record('unchanged', True)
        assert reuse.payload_identity(warm) == baseline
        record('timestamps', True, lambda: os.utime(source / 'App/Program.cs', (1800000000, 1800000000)))
        record('source-change', False, lambda: (source / 'App/Program.cs').write_text('System.Console.WriteLine(Value.Text + "-changed");'))
        record('after-change', True)
        def generation():
            return state / 'generations' / json.loads((state / 'current.json').read_text())['generation']
        record('missing-payload', False, lambda: (generation() / 'payload/runner/ActionRunner.dll').unlink())
        record('corrupt-payload', False, lambda: (generation() / 'payload/BUILD.bazel').write_text('broken'))
        record('corrupt-manifest', False, lambda: (generation() / 'manifest.json').write_text('{}'))
        record('corrupt-pointer', False, lambda: (state / 'current.json').write_text('{'))
        record('missing-pointer', False, lambda: (state / 'current.json').unlink())
        # A killed writer's unfinished directory must be ignored and removed.
        pending = state / 'generations/.pending-interrupted'
        pending.mkdir()
        (pending / 'partial').write_text('partial')
        record('interrupted-staging', True)
        assert not pending.exists()
        # Failure at the commit switch leaves the previously committed pointer intact.
        pointer = (state / 'current.json').read_bytes()
        (source / 'App/Program.cs').write_text('System.Console.WriteLine(Value.Text);')
        atomic = reuse.atomic_json
        def interrupted(path, value):
            if path.name == 'current.json': raise OSError('injected publication interruption')
            return atomic(path, value)
        with patch.object(reuse, 'atomic_json', side_effect=interrupted):
            try:
                record('interrupted-commit', False)
            except OSError as error:
                assert 'injected publication' in str(error)
            else: raise AssertionError('publication interruption did not fail')
        assert (state / 'current.json').read_bytes() == pointer
        assert not (output / 'interrupted-commit').exists()
        report['cases']['interrupted-commit'] = dict(previousPointerPreserved=True, consumerAbsent=True)
        record('recovered-publication', False)
        # A second process announces its attempt before entering prepared_view.
        # It must remain blocked for the entire first consumer context.
        child_code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from preparation_reuse import prepared_view
print('attempting', flush=True)
with prepared_view(sys.argv[2], sys.argv[3], sys.argv[4], json.loads(sys.argv[5])) as result:
    print(json.dumps(result), flush=True)
"""
        with reuse.prepared_view(source, state, output / 'first-consumer', entries) as first:
            child = subprocess.Popen([sys.executable, '-c', child_code, str(reuse.ROOT / 'tools'),
                str(source), str(state), str(output / 'second-consumer'), json.dumps(entries)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            try:
                assert child.stdout.readline().strip() == 'attempting'
                try: child.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
                else: raise AssertionError('concurrent consumer bypassed lease')
                assert not (output / 'second-consumer').exists()
            except BaseException:
                child.kill()
                child.communicate()
                raise
        stdout, stderr = child.communicate(timeout=180)
        assert child.returncode == 0, stderr
        second = json.loads(stdout)
        assert first['reused'] and second['reused'], (first, second)
        report['cases']['concurrent-consumers'] = dict(serialized=True, bothReused=True)
        # Bind a real materialization input independently of GraphExport identity.
        runner = reuse.ROOT / 'tools/ActionRunner/Build/Action.props'
        original = runner.read_bytes()
        try:
            runner.write_bytes(original + b'\n')
            record('runner-tool-change', False)
        finally:
            runner.write_bytes(original)
        record('runner-tool-restored', False)
        # Recreate restore metadata at the consumer source path, then delete producer.
        relocated = output / 'relocated-source'
        shutil.copytree(source, relocated)
        for path in relocated.rglob('*'):
            if path.is_file() and 'obj' in path.relative_to(relocated).parts:
                path.write_bytes(path.read_bytes().replace(str(source).encode(), str(relocated).encode()))
        shutil.rmtree(source)
        source = relocated
        shutil.rmtree(cold)
        shutil.rmtree(warm)
        recovered = output / 'recovered'
        with reuse.prepared_view(source, state, recovered, entries) as result:
            assert result['reused'], result
            shutil.rmtree(source)
            bazel = Path(os.environ.get('RULES_MSBUILD_BAZEL', reuse.ROOT / '.tools/bin/bazel'))
            execution = output / 'execution.json'
            run('recovered-build', [bazel, '--batch', '--nohome_rc', '--noworkspace_rc',
                '--output_base=' + str(output / 'bazel-base'), 'build', '//:all',
                '--disk_cache=' + str(output / 'empty-disk-cache'), '--spawn_strategy=darwin-sandbox',
                '--strategy=MsbuildProject=darwin-sandbox', '--jobs=2', '--noshow_progress',
                '--execution_log_json_file=' + str(execution)], recovered)
            actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
            assert len(actions) == 2 and all(not r.get('cacheHit') and r.get('runner') == 'darwin-sandbox' for r in actions), actions
            graph = json.loads((recovered / 'graph.json').read_text())
            app = next(n['id'] for n in graph['nodes'] if n['project'] == 'workspace/App/App.csproj')
            actual = run('recovered-app', [SDK / 'dotnet', recovered / f'bazel-bin/node_{app}.bundle/artifacts/App/bin/Release/net10.0/App.dll'], recovered)
            assert actual == 'recovered-rul6', actual
            report['cases']['producer-free-execution'] = dict(**result, output=actual, nativeActions=len(actions), producerAbsent=True)
        report['accepted'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(probe(parser.parse_args().output), indent=2))
