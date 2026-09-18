"""Fresh Serilog consumers restored to independent NuGet global caches."""
import argparse
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import native_workflow
from native_workflow import Workflow, BAZEL, DOTNET_ROOT, remove_tree
from probe_native_workflow import PROJECT, TESTS, APPROVED
from probe_serilog_tests import REVISION
from probe_http_cache import CacheServer
from protected_store import ProtectedStore
import remote_preparation
from portable_cache import sha


def probe(checkout, packages, output, repetitions=1, *, delay_ms=10, download_mbps=0, upload_mbps=0, measurements_only=False):
    if repetitions < 1 or any(not math.isfinite(v) or v < 0 for v in (delay_ms, download_mbps, upload_mbps)):
        raise ValueError('positive repetitions and finite nonnegative network parameters required')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(accepted=False, cases=[], scope='Serilog; native macOS ARM64; independent restored global caches; deleted producer; shaped loopback HTTP; profile recorded below')
    report['network'] = dict(delayMs=delay_ms, downloadMbps=download_mbps, uploadMbps=upload_mbps, shapedLoopback=True)
    archive = subprocess.check_output(['git', '-C', str(checkout), 'archive', REVISION])
    states = []
    def fixture(base):
        base.mkdir()
        source = base / 's'; cache = base / 'nuget'
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar: tar.extractall(source, filter='data')
        shutil.copytree(packages, cache)
        restore(source, cache)
        assert not (source / '.nuget/packages').exists()
        return source, cache
    def restore(source, cache):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'msbuild', PROJECT, '-t:Restore', '-p:Configuration=Release', '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'],
            cwd=source, env=dict(os.environ, NUGET_PACKAGES=str(cache)), capture_output=True, text=True, timeout=180)
        (source.parent / 'restore.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stderr
    def workflow(base, source, cache, endpoint, key=None):
        state = base / 'state'; states.append(state)
        return Workflow(source, state, PROJECT, tests=TESTS, protected_store=ProtectedStore(), remote_endpoint=endpoint, remote_snapshot_digest=key, nuget_packages=cache)
    def shutdown(state):
        if (state / 'g').exists(): subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'), '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', capture_output=True, check=True)
    def save(): (output / 'report.json').write_text(json.dumps(report, indent=2))
    try:
        with CacheServer() as server:
            endpoint = server.url + '/native'; producer = output / 'p'; source, cache = fixture(producer)
            w = workflow(producer, source, cache, endpoint)
            baseline = w.run(producer / 'build', operation='test'); report['producer'] = baseline
            assert baseline['accepted'] and baseline['nuget']['staged'] and baseline['compiles'] == 2
            key = baseline['remote']['publishedSnapshot']; descriptor = json.loads(server.data['/native/cas/' + key])
            prep_data = server.data['/native/cas/' + descriptor['preparation']]
            import zipfile
            with zipfile.ZipFile(io.BytesIO(prep_data)) as z: metadata = json.loads(z.read('remote.json'))
            package_blobs = {p['blob'] for p in metadata['packages']}; assert package_blobs
            component_blobs = {p['blob'] for p in metadata.get('components', [])}
            if 'evidence' in metadata: component_blobs.add(metadata['evidence'])
            # Standalone recovery proves remote package fallback when no local
            # package cache is available to the reconstruction step.
            pointer = json.loads((w.state / 'preparation/current.json').read_text())
            request = json.loads((w.state / 'preparation/generations' / pointer['generation'] / 'manifest.json').read_text())['request']
            start = len(server.events)
            fallback = remote_preparation.unpack(prep_data, output / 'fallback', request, endpoint=endpoint)
            assert fallback['packageReuse']['remotePackages'] == len(package_blobs)
            report['remotePackageFallback'] = dict(reuse=fallback['packageReuse'], transport=server.totals(start))
            remove_tree(output / 'fallback')
            original = server.data.copy(); shutdown(w.state); remove_tree(producer)
            from probe_http_cache import Bandwidth
            server.delay_ms = delay_ms; server.download = Bandwidth(download_mbps); server.upload = Bandwidth(upload_mbps)
            cases = [(f'{rep}-{case}', case) for rep in range(repetitions) for case in (('unchanged', 'body', 'package') if measurements_only else ('unchanged', 'body'))]
            if not measurements_only: cases += [(case, case) for case in ('api', 'package', 'missing-global', 'tampered-global', 'corrupt-remote-package', 'failed-test', 'lease-mutation')]
            for label, case in cases:
                base = output / label; source, cache = fixture(base)
                with server.lock: server.data = original.copy()
                if case == 'body':
                    path = source / 'src/Serilog/Log.cs'; path.write_text(path.read_text().replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);', 'public static bool IsEnabled(LogEventLevel level) => false;'))
                if case == 'api':
                    path = source / 'src/Serilog/Log.cs'; path.write_text(path.read_text() + '\n/// <summary>Cache test.</summary>\npublic class CacheApiAddition {}\n')
                if case == 'package':
                    path = source / 'src/Serilog/Serilog.csproj'; path.write_text(path.read_text().replace('Version="1.15.0"', 'Version="1.16.0"')); restore(source, cache)
                if case == 'missing-global': remove_tree(cache / 'shouldly/4.2.1')
                if case == 'tampered-global':
                    path = cache / 'shouldly/4.2.1/buildTransitive/Shouldly.targets'; path.write_bytes(path.read_bytes() + b'\n<!-- tampered -->\n')
                if case == 'corrupt-remote-package':
                    for blob in package_blobs: server.data['/native/cas/' + blob] = b'corrupt'
                if case == 'failed-test':
                    path = source / APPROVED; path.write_text(path.read_text() + '\nintentional mismatch\n')
                start = len(server.events); w = workflow(base, source, cache, endpoint, key)
                actual_generate = native_workflow.generate
                def mutate(plan, view, *args):
                    result = actual_generate(plan, view, *args)
                    path = view / 'src/Serilog/Log.cs'; path.write_bytes(path.read_bytes() + b'\n// mutation\n'); return result
                try:
                    from contextlib import nullcontext
                    with patch('native_workflow.generate', side_effect=mutate) if case == 'lease-mutation' else nullcontext():
                        result = w.run(base / 'build', operation='build' if case == 'api' else 'test', force_tests=True)
                except (ValueError, RuntimeError):
                    if case not in ('missing-global', 'tampered-global', 'failed-test', 'lease-mutation'): raise
                    result = json.loads((base / 'build/report.json').read_text())
                if case == 'unchanged':
                    assert result['runtimeHashes'] == baseline['runtimeHashes']
                    assert not any(e['method'] == 'PUT' and e['path'].rsplit('/', 1)[1] in component_blobs for e in server.events[start:])
                if case == 'body': assert result['runtimeHashes'] != baseline['runtimeHashes']
                failure = case in ('missing-global', 'tampered-global', 'failed-test', 'lease-mutation')
                assert result['accepted'] != failure, (case, result)
                events = server.events[start:]
                if failure:
                    assert not any(e['method'] == 'PUT' for e in events)
                    assert not (w.state / 'cache.json').exists()
                else:
                    assert 'publishedSnapshot' in result['remote'], result['remote']
                    assert result['compiles'] == (1 if case == 'body' else 2 if case in ('api', 'package') else 0)
                    if case != 'api': assert result['test']['passed'] and result['test']['runtimeHashes'] == result['runtimeHashes']
                    if case in ('unchanged', 'body', 'api', 'corrupt-remote-package'):
                        assert not result['preparation']['discoveryExecuted'], result['preparation']
                        reuse = result['preparation']['remotePackages']
                        assert reuse['localPackages'] == len(package_blobs) and reuse['remotePackages'] == 0, reuse
                        assert not any(e['method'] == 'GET' and e['path'].rsplit('/', 1)[1] in package_blobs for e in events)
                    if case in ('unchanged', 'body'):
                        assert not any(e['method'] == 'PUT' and e['path'].rsplit('/', 1)[1] in package_blobs for e in events)
                report['cases'].append(dict(case=case, label=label, result=result, transport=server.totals(start)))
                save(); print(label, round(result['seconds'], 3), result.get('compiles'), server.totals(start), flush=True); shutdown(w.state)
            report['accepted'] = True
    finally:
        save()
        for state in states: shutdown(state)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('checkout', 'packages', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--delay-ms', type=float, default=10)
    p.add_argument('--download-mbps', type=float, default=0)
    p.add_argument('--upload-mbps', type=float, default=0)
    p.add_argument('--measurements-only', action='store_true')
    a = p.parse_args(); probe(a.checkout, a.packages, a.output.resolve(), a.repetitions, delay_ms=a.delay_ms, download_mbps=a.download_mbps, upload_mbps=a.upload_mbps, measurements_only=a.measurements_only)
