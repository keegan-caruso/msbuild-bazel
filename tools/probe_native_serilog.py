"""Opt-in pinned Serilog acceptance for the native project cache and HTTP broker."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from native_graph import prepare_native
from portable_cache import environment, publish, seed, tool_identity
from preparation_identity import digest
from prepare_graph import DOTNET_ROOT, ROOT
from protected_store import ProtectedStore
from probe_bazel import json_stream
from probe_graph_execution import BAZEL
from probe_http_cache import CacheServer
from probe_serilog_tests import REVISION, PROJECT, APPROVED, parse_results
from starlark import call

LIBRARY = 'src/Serilog/Serilog.csproj'
TEST_SOURCE = 'test/Serilog.ApprovalTests/ApiApprovalTests.cs'
# These are the pinned SDK wrapper imports, also declared to the Bazel action.
IMPORTS = [Path('/nix/store/dfhdbgnvv0jm1ld0hrzfaklgigvl7bzp-extra.targets'),
           Path('/nix/store/hm53cqanyh9f8dl3bij21iyhvk1mlb30-sign-apphost.proj')]


def hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


def remove_owned_tree(path):
    # Bazel seals output tree directories read-only; only remove this probe root.
    for child in path.rglob("*"):
        if child.is_dir() and not child.is_symlink(): child.chmod(0o700)
    path.chmod(0o700)
    shutil.rmtree(path)


def probe(source, packages, output):
    source, packages, output = (Path(p).resolve() for p in (source, packages, output))
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
        raise ValueError('wrong pinned Serilog revision')
    archive = subprocess.check_output(['git', '-C', str(source), 'archive', REVISION])
    output.mkdir(parents=True, exist_ok=False)
    report = dict(accepted=False, revision=REVISION, sourceArchiveSha256=hashlib.sha256(archive).hexdigest(),
                  scope='Serilog Release/net10.0; same-host macOS ARM64 Nix; explicit loopback HTTP snapshots', cases=[])
    dotnet = DOTNET_ROOT / 'dotnet'
    home, temp = output / 'home', output / 'tmp'
    home.mkdir(); temp.mkdir()

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(label, args, cwd, *, env=None, failure=False):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True, text=True, timeout=900)
        (output / (label + '.log')).write_text(result.stdout + result.stderr)
        if (result.returncode != 0) != failure:
            raise AssertionError(label + ': unexpected exit ' + str(result.returncode) + '\n' + result.stdout[-2000:] + result.stderr[-2000:])
        return result

    run('bootstrap', [dotnet, 'build', ROOT / 'tools/NativeProjectCache', '-c', 'Release'], ROOT)
    run('exporter', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release'], ROOT)
    runners = sorted((ROOT / 'tools/NativeProjectCache/bin/Release/net10.0').glob('NativeProjectCache.*'))
    runners = [p for p in runners if p.suffix in ('.dll', '.json')]
    sdk_identity = digest(ProtectedStore().snapshot(DOTNET_ROOT.parents[1], [Path('/nix/store')]))
    identity = tool_identity(sdk_identity, runners, sorted((ROOT / 'tools').glob('*.py')), IMPORTS)
    report['toolchain'] = identity

    def fixture(label):
        path = output / label
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            contents.extractall(path, filter='data')
        shutil.copytree(packages, path / '.nuget/packages')
        return path

    def prepare(label, path, entry=PROJECT):
        env = environment(DOTNET_ROOT, home, temp, path)
        run(label + '-restore', [dotnet, 'msbuild', entry, '-t:Restore', '-p:Configuration=Release',
            '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], path, env=env)
        graph, request = output / (label + '-graph.json'), output / (label + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(path), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.400', packageRoot=str(path / '.nuget/packages'), entryPoints=[dict(project=entry,
            globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})], output=str(graph))))
        run(label + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], path, env=env)
        plan = output / (label + '-plan')
        prepare_native(path, graph, plan, toolchain=identity)
        return plan

    def raw(label, path, entry=PROJECT):
        env = environment(DOTNET_ROOT, home, temp, path)
        run(label, [dotnet, 'msbuild', entry, '-t:Rebuild', '-p:Configuration=Release', '-p:TargetFramework=net10.0',
            '-p:PathMap=' + str(path) + '=/_/workspace', '-nodeReuse:false', '-nologo'], path, env=env)
        result = hashes(path / Path(entry).parent / 'bin/Release/net10.0')
        # Static graph does not request the coverage package's extra source-map
        # target. This absolute-path diagnostic is not an execution dependency.
        sidecar = '.msCoverageSourceRootsMapping_Serilog.ApprovalTests'
        if sidecar in result:
            report.setdefault('rawOnlyDiagnostics', {})[label] = {sidecar: result.pop(sidecar)}
        return result

    def test(label, bundle, path, failure=False):
        work = output / (label + '-data')
        for relative in (TEST_SOURCE, APPROVED):
            dest = work / relative; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path / relative, dest)
        env = environment(DOTNET_ROOT, home, temp, work)
        env.update(CI='true', DiffEngine_Disabled='true', SHOULDLY_SOURCE_PATH_MAP=str(work) + '=/_/workspace')
        before = hashes(bundle / 'app')
        results = output / (label + '-results')
        run(label, [dotnet, 'vstest', bundle / 'app/Serilog.ApprovalTests.dll',
            '--logger:trx;LogFileName=results.trx', '--ResultsDirectory:' + str(results)], work, env=env, failure=failure)
        result = parse_results(results / 'results.trx')
        assert result['passed'] == (0 if failure else 1) and result['failed'] == (1 if failure else 0)
        assert before == hashes(bundle / 'app'), 'test changed runtime'
        report['cases'].append(dict(label=label, test=result)); save()

    startup = [BAZEL, '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(output / 'b'),
               '--output_user_root=' + str(output / 'u')]
    catalog = []
    with CacheServer() as server:
        def build(label, plan, compiles, *, failure=False, snapshot=None):
            nonlocal catalog
            g = output / (label + '-g'); g.mkdir()
            shutil.copytree(plan / 'src', g / 'src')
            for name in ('manifest.json', 'restore.json'): shutil.copyfile(plan / name, g / name)
            manifest = json.loads((g / 'manifest.json').read_text())
            seeded = seed(server.url + '/native', catalog if snapshot is None else snapshot, manifest, g / 'seeds')
            for p in runners:
                dest = g / 'runner' / p.name; dest.parent.mkdir(exist_ok=True); shutil.copyfile(p, dest)
            for name in ('msbuild.bzl', 'native_cache.bzl'): shutil.copyfile(ROOT / 'bazel' / name, g / name)
            (g / 'MODULE.bazel').write_text('module(name="native_serilog_probe")\nbazel_dep(name="platforms",version="0.0.11")\nlocal_dotnet_sdk=use_repo_rule("//:msbuild.bzl","local_dotnet_sdk")\n' +
                call('local_dotnet_sdk', name='dotnet', path=str(DOTNET_ROOT), external_imports=list(map(str, IMPORTS))))
            (g / 'BUILD.bazel').write_text('load(":native_cache.bzl","msbuild_native_cache")\n' + call('msbuild_native_cache',
                name='n', project=json.loads((plan / 'entry.json').read_text())['entry'],
                srcs=sorted('src/' + p for p in hashes(g / 'src')),
                seeds=sorted('seeds/' + p for p in hashes(g / 'seeds')), manifest='manifest.json', restore='restore.json',
                runner='runner/NativeProjectCache.dll', runner_support=['runner/NativeProjectCache.deps.json', 'runner/NativeProjectCache.runtimeconfig.json'],
                sdk='@dotnet//:files', dotnet='@dotnet//:sdk/dotnet', execution_nonce=label))
            execution = output / (label + '-execution.json')
            start = len(server.events)
            run(label, [*startup, 'build', '//:n', '--incompatible_autoload_externally=', '--jobs=2',
                '--spawn_strategy=darwin-sandbox', '--strategy=MsbuildNativeCache=darwin-sandbox',
                '--execution_log_json_file=' + str(execution), '--noshow_progress', '--color=no', '--curses=no'], g, failure=failure)
            assert not any(e['path'].startswith('/native/') for e in server.events[start:]), 'action contacted broker'
            if failure:
                assert 'error CS' in (output / (label + '.log')).read_text(), 'expected compiler failure'
                report['cases'].append(dict(label=label, failedBuild=True, publicationAttempted=False)); save(); return None
            actions = [a for a in json_stream(execution) if a.get('mnemonic') == 'MsbuildNativeCache']
            assert len(actions) == 1 and actions[0].get('runner') == 'darwin-sandbox' and not actions[0].get('cacheHit'), 'fresh native action required'
            bundle = g / 'bazel-bin/n.bundle'
            diagnostics = g / 'bazel-bin/n.diagnostics'
            actual = json.loads((diagnostics / 'action.json').read_text())['compiles']
            events = json.loads((diagnostics / 'events.json').read_text())
            assert actual == compiles, (label, actual, compiles)
            evidence = output / (label + '-bundle'); shutil.copytree(bundle, evidence)
            published = publish(server.url + '/native', evidence / 'cache', verified_blobs=seeded['verifiedBlobs'])
            assert not published['errors']; catalog = published['entries']
            item = dict(label=label, compiles=actual, hits=sum(e['kind'] == 'hit' for e in events),
                rejectedSeeds=seeded['rejected'], runtimeHashes=hashes(evidence / 'app'), nativeSandbox=True)
            report['cases'].append(item); save(); print(label, actual, item['hits'], flush=True)
            return evidence

        try:
            producer = fixture('producer'); plan = prepare('cold', producer)
            baseline = raw('raw', producer)
            cold = build('cold', plan, 2); assert hashes(cold / 'app') == baseline, 'ordinary MSBuild runtime differs'
            test('cold-test', cold, producer)
            snapshot = catalog.copy()
            consumer = fixture('consumer'); relocated = prepare('relocated', consumer)
            assert (plan / 'manifest.json').read_bytes() == (relocated / 'manifest.json').read_bytes(), 'relocated identity differs'
            # Producer sources, plan, runner outputs and local action outputs are absent.
            remove_owned_tree(producer); remove_owned_tree(plan); remove_owned_tree(cold)
            remove_owned_tree(output / 'cold-g')
            run('clear-local', [*startup, 'shutdown'], ROOT)
            remove_owned_tree(output / 'b')
            recovered = build('recovered', relocated, 0, snapshot=snapshot)
            assert hashes(recovered / 'app') == baseline
            test('recovered-test', recovered, consumer)
            for label, relative in [('stale-source', TEST_SOURCE),
                                    ('stale-package', '.nuget/packages/shouldly/4.2.1/shouldly.4.2.1.nupkg')]:
                item = consumer / relative; original_input = item.read_bytes()
                rejected = output / (label + '-plan')
                try:
                    item.write_bytes(original_input + b'\nchanged-input\n')
                    try:
                        prepare_native(consumer, output / 'relocated-graph.json', rejected, toolchain=identity)
                    except (ValueError, RuntimeError) as error:
                        assert any(word in str(error).lower() for word in ('stale', 'hash')), str(error)
                        assert not rejected.exists(), 'invalid plan published'
                        report['cases'].append(dict(label=label, rejection=str(error)))
                    else: raise AssertionError('changed input accepted')
                finally: item.write_bytes(original_input)
            approved = consumer / APPROVED; original = approved.read_bytes()
            approved.write_bytes(original + b'\nintentional approval mismatch\n')
            test('golden-mismatch', recovered, consumer, True); approved.write_bytes(original)
            library_plan = prepare('library', consumer, LIBRARY)
            lib = build('library', library_plan, 1, snapshot=[])
            assert hashes(lib / 'app') == raw('library-raw', consumer, LIBRARY)
            lib_recovered = build('library-recovered', library_plan, 0)
            assert hashes(lib_recovered / 'app') == hashes(lib / 'app')
            # Return to the original two-node catalog for all mutation controls.
            catalog = snapshot.copy()
            code = consumer / TEST_SOURCE; original_code = code.read_text()
            code.write_text(original_code.replace('        var assembly =', '        if (DateTime.UtcNow.Year > 0) throw new InvalidOperationException("intentional-test-exception");\n        var assembly ='))
            changed = prepare('test-edit', consumer)
            edited = build('test-edit', changed, 1)
            test('exception-test', edited, consumer, True)
            assert 'intentional-test-exception' in (output / 'exception-test.log').read_text()
            code.write_text(original_code); catalog = snapshot.copy()
            body = consumer / 'src/Serilog/Log.cs'; original_body = body.read_text()
            # A private method changes implementation bytes without adding public API.
            body.write_text(original_body.replace('public static class Log\n{', 'public static class Log\n{\n    static int NativeCacheBodyProbe() => 42;'))
            assert body.read_text() != original_body
            # Adding a method before an async method changes its generated state-machine
            # name in reference metadata. It is not a stable-reference body control.
            changed = prepare('private-member-edit', consumer)
            build('private-member-edit', changed, 2)
            catalog = snapshot.copy()
            body.write_text(original_body.replace('public static bool IsEnabled(LogEventLevel level) => Logger.IsEnabled(level);',
                                                 'public static bool IsEnabled(LogEventLevel level) => false;'))
            changed = prepare('body-edit', consumer)
            edited = build('body-edit', changed, 1)
            def library_reference(bundle):
                refs = list((bundle / 'cache').glob('*/artifacts/src/Serilog/obj/Release/net10.0/ref/Serilog.dll'))
                assert len(refs) == 1
                return hashlib.sha256(refs[0].read_bytes()).hexdigest()
            assert library_reference(edited) == library_reference(recovered), 'body edit changed reference assembly'
            assert hashes(edited / 'app') == raw('body-raw', consumer)
            test('body-test', edited, consumer)
            body.write_text(original_body.replace('public static class Log\n{', 'public static class Log\n{\n    /// <summary>Cache invalidation acceptance probe.</summary>\n    public static int NativeCacheApiProbe() => 42;'))
            catalog = snapshot.copy()
            changed = prepare('api-edit', consumer)
            edited = build('api-edit', changed, 2)
            assert hashes(edited / 'app') == raw('api-raw', consumer)
            test('api-mismatch', edited, consumer, True)
            body.write_text(original_body); catalog = snapshot.copy()
            project = consumer / LIBRARY; original_project = project.read_text()
            project.write_text(original_project.replace('Version="1.15.0"', 'Version="1.16.0"'))
            changed = prepare('generator-edit', consumer)
            edited = build('generator-edit', changed, 2)
            assert hashes(edited / 'app') == raw('generator-raw', consumer)
            test('generator-test', edited, consumer)
            project.write_text(original_project); catalog = snapshot.copy()
            victim = next(r for r in catalog if r['project'] == LIBRARY)
            server.data['/native/cas/' + victim['blob']] = b'corrupt'
            repaired = build('corrupt', relocated, 1)
            assert report['cases'][-1]['rejectedSeeds'] and hashes(repaired / 'app') == baseline
            victim = next(r for r in catalog if r['project'] == LIBRARY)
            server.data.pop('/native/cas/' + victim['blob'])
            repaired = build('missing', relocated, 1)
            assert report['cases'][-1]['rejectedSeeds'] and hashes(repaired / 'app') == baseline
            # The graph remains evaluable but compilation must fail; no broker publication.
            code.write_text(original_code + '\nthis is invalid C sharp\n')
            failed = prepare('failed', consumer)
            before = dict(server.data); build('failed', failed, 0, failure=True)
            assert server.data == before, 'failed build published cache bytes'
            report['accepted'] = True
        except BaseException as error:
            report['failure'] = str(error); raise
        finally:
            run('shutdown', [*startup, 'shutdown'], ROOT)
            (output / 'http-events.json').write_text(json.dumps(server.events, indent=2))
            save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'): parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    probe(args.source, args.packages, args.output)
