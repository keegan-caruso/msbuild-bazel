"""Real Serilog remote preparation with deleted producer and fresh consumers."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from contextlib import nullcontext
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import native_workflow
from native_workflow import Workflow, BAZEL, DOTNET_ROOT, remove_tree
from probe_native_workflow import fixture, PROJECT, TESTS, APPROVED
from probe_http_cache import CacheServer
from protected_store import ProtectedStore


def probe(checkout, packages, output):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(accepted=False, cases=[], scope='pinned Serilog; fresh state; same-host macOS ARM64; loopback HTTP')
    states = []
    def shutdown(state):
        if (state / 'g').exists():
            subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
                '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', check=True, capture_output=True)
    def save(): (output / 'report.json').write_text(json.dumps(report, indent=2))
    try:
        with CacheServer() as server:
            endpoint = server.url + '/native'
            producer = output / 'p'; producer.mkdir()
            source = fixture(checkout, packages, producer / 's'); state = producer / 'state'; states.append(state)
            baseline = Workflow(source, state, PROJECT, tests=TESTS, protected_store=ProtectedStore(), remote_endpoint=endpoint).run(producer / 'build', operation='test')
            assert baseline['accepted'] and baseline['compiles'] == 2
            key = baseline['remote']['publishedSnapshot']
            descriptor = json.loads(server.data['/native/cas/' + key]); assert descriptor['preparation']
            original = server.data.copy()
            report['producer'] = baseline
            shutdown(state); remove_tree(producer)
            for case in ('unchanged', 'body', 'api', 'new-source', 'package', 'corrupt-preparation', 'missing-snapshot', 'corrupt-bundle', 'failed-test', 'failed-compile', 'lease-mutation'):
                base = output / case; base.mkdir()
                source = fixture(checkout, packages, base / 's'); state = base / 'state'; states.append(state)
                with server.lock: server.data = original.copy()
                if case == 'body':
                    path = source / 'src/Serilog/Log.cs'
                    path.write_text(path.read_text().replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);', 'public static bool IsEnabled(LogEventLevel level) => false;'))
                if case == 'api':
                    path = source / 'src/Serilog/Log.cs'; path.write_text(path.read_text() + '\n/// <summary>Remote API invalidation control.</summary>\npublic class RemoteApiAddition {}\n')
                if case == 'new-source': (source / 'src/Serilog/RemoteNew.cs').write_text('namespace Serilog; internal class RemoteNew {}\n')
                if case == 'package':
                    path = source / 'src/Serilog/Serilog.csproj'; path.write_text(path.read_text().replace('Version="1.15.0"', 'Version="1.16.0"'))
                    import os
                    subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'msbuild', PROJECT, '-t:Restore', '-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], cwd=source,
                        env=dict(os.environ, NUGET_PACKAGES=str(source / '.nuget/packages')), check=True)
                if case == 'corrupt-preparation': server.data['/native/cas/' + descriptor['preparation']] = b'corrupt'
                if case == 'missing-snapshot': del server.data['/native/cas/' + key]
                if case == 'corrupt-bundle': server.data['/native/cas/' + descriptor['projects'][0]['blob']] = b'corrupt'
                if case == 'failed-compile':
                    path = source / 'src/Serilog/Log.cs'; path.write_text(path.read_text() + '\ninvalid csharp;\n')
                if case == 'failed-test':
                    path = source / APPROVED; path.write_text(path.read_text() + '\nintentional mismatch\n')
                event = len(server.events)
                workflow = Workflow(source, state, PROJECT, tests=TESTS, protected_store=ProtectedStore(), remote_endpoint=endpoint, remote_snapshot_digest=key)
                actual_generate = native_workflow.generate
                def mutate_lease(plan, view, *args):
                    result = actual_generate(plan, view, *args)
                    path = view / 'src/Serilog/Log.cs'; path.write_bytes(path.read_bytes() + b'\n// changed during lease\n')
                    return result
                try:
                    with patch('native_workflow.generate', side_effect=mutate_lease) if case == 'lease-mutation' else nullcontext():
                        result = workflow.run(base / 'build', operation='build' if case in ('api', 'failed-compile') else 'test', force_tests=True)
                except (RuntimeError, ValueError) as error:
                    if case not in ('failed-test', 'failed-compile', 'lease-mutation'): raise
                    if case == 'lease-mutation': assert 'changed during consumption' in str(error), str(error)
                    result = json.loads((base / 'build/report.json').read_text())
                assert result['accepted'] == (case not in ('failed-test', 'failed-compile', 'lease-mutation')), (case, result)
                if case in ('failed-test', 'failed-compile', 'lease-mutation'):
                    assert not (state / 'cache.json').exists()
                    assert not any(e['method'] == 'PUT' for e in server.events[event:]), 'failed test published remotely'
                else:
                    assert 'publishedSnapshot' in result['remote'], result['remote']
                    if case != 'api':
                        assert result['test']['passed'] and result['test']['runtimeHashes'] == result['runtimeHashes']
                if case in ('unchanged', 'body', 'api', 'corrupt-bundle'):
                    assert not result['preparation']['discoveryExecuted'], (case, result['preparation'])
                if case in ('new-source', 'package', 'corrupt-preparation', 'missing-snapshot'):
                    assert result['preparation']['discoveryExecuted'], (case, result['preparation'])
                expected = {'unchanged': 0, 'body': 1, 'api': 2, 'new-source': 2, 'package': 2, 'corrupt-preparation': 0, 'missing-snapshot': 2, 'corrupt-bundle': 1, 'failed-test': 0, 'failed-compile': 1, 'lease-mutation': 0}
                assert result['compiles'] == expected[case], (case, result['compiles'])
                report['cases'].append(dict(case=case, result=result, transport=server.totals(event)))
                save(); print(case, result['compiles'], result['preparation']['reason'], flush=True)
                shutdown(state)
            report['accepted'] = True
    finally:
        save()
        for state in states: shutdown(state)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('checkout', 'packages', 'output'): p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args(); probe(a.checkout, a.packages, a.output.resolve())
