"""Independent public-worker project-cache recovery for reviewed runtime slices.

Use a new producer/consumer output base and a separate consumer container. Whole
Bazel disk/remote action caches are disabled. Stop the producer before recovery.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from runtime_benchmark import IMPLEMENTATION, REFERENCE, IMPL_DLL, REF_DLL, expand_raw_packages
from runtime_root_properties import root_properties

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path, help='new disposable results directory')
    parser.add_argument('--output-base', type=Path, required=True, help='unused base; no local graph results')
    parser.add_argument('--slice', choices=['pipelines', 'loaded-common', 'runtime-suites'], default='pipelines')
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'])
    parser.add_argument('--reuse-producer-base', action='store_true', help='retain producer repository/native setup; shutdown clears project snapshots before seed')
    parser.add_argument('--reuse-consumer-base', action='store_true', help='retain consumer repository/preparation setup; require a fresh broker namespace and abandoned-state reclamation')
    parser.add_argument('--qualified-raw-results', type=Path, help='same-consumer full-source raw baseline for runtime-suite edit parity')
    parser.add_argument('--seed-evidence', type=Path, help='producer seed.json; required for consumer')
    parser.add_argument('--edits', action='store_true', help='consumer body/API remote recovery and fresh native controls')
    parser.add_argument('--diagnostics', action='store_true', help='separate profiled recovery for logical transfer counters; excluded from scored rows')
    parser.add_argument('--raw-control', action='store_true', help='fresh raw graph Restore/Build in the same consumer, after restoring original sources')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == (args.seed_evidence is not None)
    assert not (args.edits or args.diagnostics or args.raw_control) or args.phase == 'consumer'
    root, results, output_base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert not args.reuse_producer_base or args.phase == 'producer'
    assert not args.reuse_consumer_base or args.phase == 'consumer'
    assert args.reuse_producer_base or args.reuse_consumer_base or not output_base.exists()
    assert args.qualified_raw_results is None or (args.slice == 'runtime-suites' and args.phase == 'consumer')
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [(project, variant) for project, declaration in contract['Projects'].items()
             for variant in declaration.get('Configurations') or [declaration]]
    assert contract['SdkVersion'] == '10.0.400' and contract['Properties']['TargetOS'] == 'linux' and contract['Properties']['TargetArchitecture'] == 'arm64'
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for _, node in nodes)
    if args.slice == 'runtime-suites':
        mutation = json.loads(Path(__file__).with_name('runtime_source_host_edit.json').read_text())
        compiled_files = 3622
    elif args.slice == 'loaded-common':
        mutation = json.loads(Path(__file__).with_name('runtime_loaded_common_edit.json').read_text())
        compiled_files = 1447
    else:
        mutation = dict(compiled=38, implementation=IMPLEMENTATION, reference=REFERENCE, implDll=IMPL_DLL, refDll=REF_DLL,
                        bodyAnchor='UseSynchronizationContext = useSynchronizationContext;',
                        implementationAnchor='public class PipeOptions\n    {', referenceAnchor='public partial class PipeOptions\n    {',
                        expectedMisses=dict(body=6, api=11), entries=['src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj'])
        compiled_files = 412
    implementation, reference = mutation['implementation'], mutation['reference']
    impl_dll, ref_dll = mutation['implDll'], mutation['refDll']
    assert count == mutation['compiled'], 'Unexpected reviewed compilation scope'
    assert (contract.get('Entries') or [contract['Entry']]) == mutation['entries'], 'Unexpected reviewed roots'
    declared = set(contract['SharedInputs']) | {p for _, n in nodes for p in n['Inputs']}
    assert {implementation, reference} <= declared
    directories = {p for _, n in nodes for p in n['OutputDirectories']}
    files = {p for _, n in nodes for p in n.get('OutputFiles', [])}
    states = {d + '/' + Path(p).name + '.GenerateResource.cache' for p, n in nodes
              for d in n['OutputDirectories'] if d.startswith('artifacts/obj/')}
    environment = dict(os.environ, USE_BAZEL_VERSION=args.version or ('8.8.0' if args.phase == 'producer' else '9.2.0'))
    endpoint = environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL')
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    environment.pop('RULES_MSBUILD_GRAPH_PROFILE', None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(output_base)]
    options = ['--jobs=' + ('1' if args.slice == 'runtime-suites' else '4'), '--strategy=MSBuildGraph=worker', '--spawn_strategy=linux-sandbox',
               '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--strategy=RuntimeNative=standalone', '--noshow_progress']
    rows = []
    stopped_workers = set()
    scratch = Path('/tmp') / ('rules-msbuild-workers-' + str(os.getuid()))
    generated, build = root / 'graph.generated.bzl', root / 'BUILD.bazel'
    original_generated, original_build = generated.read_bytes(), build.read_bytes()
    main_line = next(line for line in original_build.splitlines() if line.startswith(b'app_graph(name="graph",'))
    assert main_line.count(b'linux_worker=True') == 1
    bootstrap = root / 'remote_bootstrap.bzl'
    assert not bootstrap.exists()
    bootstrap.write_text('def _bootstrap(ctx):\n    return [DefaultInfo(files = ctx.attr.runner[DefaultInfo].files)]\n'
                         'remote_bootstrap = rule(implementation = _bootstrap, attrs = {"runner": attr.label(cfg = "exec", mandatory = True)})\n')
    active_build = original_build + b'\nload(":remote_bootstrap.bzl", "remote_bootstrap")\nremote_bootstrap(name="remote_bootstrap",runner=":graph_runner")\n'
    build.write_bytes(active_build)
    originals = {p: (root / p).read_bytes() for p in [implementation, reference]}
    nonce = root / 'remote-request.txt'
    assert not nonce.exists()
    prefix, action = original_generated.decode().split('    msbuild_graph(\n')
    assert action.count('        srcs = [') == 1
    generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["remote-request.txt",', 1))

    def invoke(arguments, label):
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(bazel + arguments, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        return time.monotonic() - start

    def stop(label):
        invoke(['shutdown'], label)
        stopped_workers.clear()
        for lease in scratch.glob('*.lease'):
            assert not lease.is_symlink()
            with lease.open('r+b') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                stopped_workers.add(lease.stem)

    def capture():
        artifact = root / 'bazel-bin/graph.graph'
        workspace = artifact / 'workspace'
        paths = {workspace / p for p in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        outputs = {str(p.relative_to(workspace)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
                   for p in paths if p.is_file() and not p.name.endswith('.AssemblyReference.cache')
                   and (str(p.relative_to(workspace)) not in states or str(p.relative_to(workspace)) in files)}
        report = json.loads((artifact / 'report.json').read_text())
        runners = list((output_base / 'execroot/_main/bazel-out').glob('*-exec*/bin/graph_runner.runner/GraphBuild.dll'))
        assert len(runners) == 1, runners
        return report, outputs, hashlib.sha256(runners[0].read_bytes()).hexdigest()

    def graph(label, hits, native=False, profile=False):
        assert not (native and profile)
        configured = active_build.replace(main_line, main_line.replace(b'linux_worker=True', b'linux_worker=False')) if native else active_build
        if profile:
            configured = configured.replace(main_line, main_line.replace(b'linux_worker=True', b'linux_worker=True,profile_build=True'))
        build.write_bytes(configured)
        nonce.write_text(str(uuid.uuid4()))
        events = results / (label + '.bep')
        strategy = options if not native else [p for p in options if p != '--strategy=MSBuildGraph=worker'] + ['--strategy=MSBuildGraph=linux-sandbox']
        arguments = ['build', '//:graph', *strategy, '--build_event_json_file=' + str(events)]
        if not native:
            arguments.append('--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint)
        seconds = invoke(arguments, label)
        metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in events.read_text().splitlines() if 'buildMetrics' in json.loads(line))
        actions = sum(int(r.get('actionsExecuted', 0)) for r in metrics.get('actionData', []) if r['mnemonic'] == 'MSBuildGraph')
        assert actions == 1, 'Must execute the graph; whole-action hits do not qualify project recovery'
        if not native:
            assert not any((scratch / name).exists() for name in stopped_workers), 'New broker did not reclaim abandoned snapshots'
            live_workers = {p.name for p in scratch.iterdir() if p.is_dir()}
            assert live_workers and live_workers.isdisjoint(stopped_workers), 'Worker must use a fresh cache namespace'
        report, outputs, runner = capture()
        assert (report['hits'], report['misses']) == (hits, count - hits), report
        assert (report['operations'] is not None) == profile and ('worker' in report) == profile
        assert report['preparedRestore'] == bool(contract.get('Restore'))
        assert report['readOnlyPreparedPackages'] == (bool(contract.get('Restore')) and not native)
        record = dict(case=label, slice=args.slice, seconds=seconds, version=environment['USE_BAZEL_VERSION'], externalWorkspace=str(root),
                      runnerSha256=runner, hits=hits, misses=count-hits, files=len(outputs), profiled=profile,
                      preparationActions=sum(int(r.get('actionsExecuted', 0)) for r in metrics.get('actionData', []) if r['mnemonic'] == 'MSBuildGraphRestore'),
                      report=report, outputs=outputs)
        (results / (label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        rows.append({k: v for k, v in record.items() if k not in ['report', 'outputs']})
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(rows[-1]), flush=True)
        return record

    def suites(label):
        if args.slice != 'runtime-suites':
            return
        suite = json.loads((root / 'suite.json').read_text())
        assert len(suite['tests']) == 8
        events = results / (label + '-tests.bep')
        seconds = invoke(['test', '//:runtime_suites', *options, '--local_test_jobs=1', '--test_output=errors',
                          '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint,
                          '--build_event_json_file=' + str(events)], label + '-tests')
        from collections import Counter
        import xml.etree.ElementTree as ET
        sys.path.insert(0, str(ROOT / 'tests/explicit_msbuild/runtime'))
        from case_names import normalize
        outcomes = Counter()
        signatures = {}
        for selection in suite['tests']:
            cases = Counter()
            for case in ET.parse(root / 'bazel-testlogs' / selection['target'].removeprefix('//:') / 'test.xml').getroot().findall('.//testcase'):
                outcome = ('failed' if case.find('failure') is not None or case.find('error') is not None else
                           'skipped' if case.find('skipped') is not None else 'passed')
                outcomes[outcome] += 1
                cases[case.get('name'), outcome] += 1
            canonical = sorted((name, outcome, count) for (name, outcome), count in normalize(cases).items())
            signatures[selection['target']] = dict(cases=sum(cases.values()), sha256=hashlib.sha256(json.dumps(canonical).encode()).hexdigest())
        if args.phase == 'consumer':
            assert signatures == json.loads((args.seed_evidence.parent / 'seed-tests.json').read_text()), 'Normalized suite cases/outcomes differ from producer'
        elif label == 'seed':
            (results / 'seed-tests.json').write_text(json.dumps(signatures, indent=2) + '\n')
        assert outcomes == Counter(passed=118952, skipped=64), outcomes
        from runtime_suite_verify import proofs
        application = json.loads((root / 'application.json').read_text())
        required = {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
        expected = {}
        for scope in ['managed', 'private']:
            for name, producer in application.get(scope, {}).items():
                expected.setdefault(name, set()).add(hashlib.sha256((root / 'bazel-bin/graph.graph/workspace' / producer['path']).read_bytes()).hexdigest().upper())
        for name, producer in application['native'].items():
            expected.setdefault(name, set()).add(hashlib.sha256((root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name).read_bytes()).hexdigest().upper())
        observations = 0
        for selection in suite['tests']:
            observed = proofs(root / 'bazel-testlogs' / selection['target'].removeprefix('//:') / 'test.outputs')
            assert observed
            for proof in observed:
                assert required <= proof['files'].keys()
                for name, value in proof['files'].items():
                    if name in expected:
                        assert value['sha256'] in expected[name], (label, name)
                        observations += 1
        row = dict(case=label + '-tests', seconds=seconds, outcomes=outcomes, normalizedCases=signatures, sourceHashObservations=observations,
                   scope='test/native-host setup separate from project-cache graph recovery')
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)

    def qualified_raw_control(label, remote_record):
        from runtime_full_source import capture_compiled_products, validate_raw_contract
        raw_results = args.qualified_raw_results.resolve()
        validate_raw_contract(contract, raw_results)
        raw = raw_results / 'raw-workspace'
        for path in originals:
            content = (root / path).read_bytes()
            if (raw / path).read_bytes() != content:
                (raw / path).write_bytes(content)
        scratch = results / 'qualified-raw-scratch'
        scratch.mkdir(exist_ok=True)
        stable = '/__rules_msbuild_graph/output/workspace'
        command = ['bash', str(Path(__file__).with_name('runtime_raw.sh')), os.environ['RULES_MSBUILD_DOTNET_ROOT'],
                   str(raw), str(scratch), stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
        reader = results / 'raw-reader'
        sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
        if not reader.exists():
            reader.mkdir()
            for source, target in [('RawTimingLog.cs.txt', 'Program.cs'), ('Inventory.csproj.txt', 'Tool.csproj')]:
                shutil.copyfile(ROOT / 'tests/explicit_msbuild/runtime' / source, reader / target)
            with (results / 'raw-reader-build.log').open('w') as log:
                subprocess.run([str(sdk / 'dotnet'), 'build', str(reader / 'Tool.csproj'), '-c', 'Release',
                                '-p:UseSharedCompilation=false'], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        binlog = label + '.binlog'
        with (results / (label + '-raw.log')).open('w') as log:
            subprocess.run(command + [stable + '/.qualification/' + binlog], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        compiled = json.loads(subprocess.check_output([str(sdk / 'dotnet'), str(reader / 'bin/Release/net10.0/Tool.dll'),
            str(raw / '.qualification' / binlog)], env=environment, text=True))['compiled']
        if label in ['body-remote', 'api-remote']:
            assert len(compiled) == mutation['expectedMisses'][label.split('-')[0]], compiled
        products = capture_compiled_products(raw, contract)
        compared = {p: v['sha256'] for p, v in remote_record['outputs'].items() if p in products}
        assert len(compared) == len(products) == compiled_files
        assert compared == {p: v['sha256'] for p, v in products.items()}, 'Independent consumer raw byte parity'
        rows.append(dict(case=label + '-raw-parity', comparedCompiledFiles=len(products), rawCompilerCalls=compiled,
                         scope='unscored diagnostic SDK graph build; binary logging enabled'))
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')

    def raw_control(seed):
        for path, content in originals.items():
            if (root / path).read_bytes() != content:
                (root / path).write_bytes(content)
        # Stop graph servers before the matched raw cold control.
        stop('raw-control-stop-broker')
        raw, scratch = results / 'raw-workspace', results / 'raw-scratch'
        shutil.copytree(root, raw, ignore=shutil.ignore_patterns('bazel-*', '.nuget', '.cache', '.cli'))
        expansion = expand_raw_packages(raw)
        scratch.mkdir()
        (raw / 'NuGet.Config').write_text('<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
        sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
        stable, stable_sdk = '/__rules_msbuild_graph/output/workspace', '/__rules_msbuild_graph/sdk'
        host = ['bash', str(ROOT / 'tests/graph_build/upstream/runtime_raw.sh'), str(sdk), str(raw), str(scratch)]
        properties = [f'-p:{k}={v}' for k, v in contract['Properties'].items()]
        common = ['-p:UseSharedCompilation=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion'],
                  '-p:PathMap=' + stable + '=/_/workspace%2C' + stable_sdk + '=/_/sdk']
        entries = contract.get('Entries') or [contract['Entry']]
        def execute(command, label):
            start = time.monotonic()
            with (results / (label + '.log')).open('w') as log:
                subprocess.run(command, cwd=raw, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
            return time.monotonic() - start
        restore_seconds = 0
        for index, entry in enumerate(entries):
            restore = host + ['restore', stable + '/' + entry, '--configfile', stable + '/NuGet.Config',
                             '--source', stable + '/.package-source', '--packages', stable + '/.nuget', '-p:NuGetAudit=false',
                             '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion']]
            restore += [f'-p:{k}={v}' for k, v in root_properties(contract, entry).items() if k.lower() != 'targetframework']
            restore_seconds += execute(restore, 'raw-restore-' + str(index))
        if len(entries) == 1:
            command = host + ['msbuild', stable + '/' + entries[0], '-graphBuild', '-m:4', '-t:Build', '-nologo', *common, *properties]
        else:
            driver = results / 'raw-driver'
            driver.mkdir()
            for source, target in [('RuntimeRawGraph.cs.txt', 'Program.cs'), ('RuntimeRawGraph.csproj.txt', 'Raw.csproj')]:
                shutil.copyfile(Path(__file__).with_name(source), driver / target)
            execute([str(sdk / 'dotnet'), 'build', str(driver / 'Raw.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false'], 'raw-driver-build')
            shutil.copytree(driver / 'bin/Release/net10.0', raw / '.qualification')
            command = host + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
        build_seconds = execute(command, 'raw-build')
        products = {p: v['sha256'] for p, v in seed['outputs'].items() if Path(p).suffix in ['.dll', '.pdb', '.resources']
                    and not (p.startswith('artifacts/obj/') and '/PreTrim/' in p)}
        raw_paths = {raw / p for p in files} | {p for d in directories for p in (raw / d).rglob('*')}
        raw_products = {str(p.relative_to(raw)): hashlib.sha256(p.read_bytes()).hexdigest() for p in raw_paths
                        if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']
                        and not (str(p.relative_to(raw)).startswith('artifacts/obj/') and '/PreTrim/' in str(p.relative_to(raw)))}
        assert len(products) == compiled_files and products == raw_products, 'Fresh consumer raw byte parity failed'
        record = dict(case='fresh-raw-compilation', observations=1, rawRestoreSeconds=restore_seconds, rawBuildSeconds=build_seconds,
                      rawWorkflowSeconds=restore_seconds + build_seconds, packageExpansionSeconds=expansion, comparedCompiledFiles=len(products),
                      scope='same consumer, SDK/packages available; fresh outputs; package expansion reported separately')
        rows.append(record)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(record), flush=True)

    try:
        if args.reuse_producer_base:
            stop('producer-empty-local-cache')
        if args.reuse_consumer_base:
            stop('consumer-empty-local-cache')
            # Bazel may kill the broker before Dispose; its next startup must
            # reclaim those unlocked namespaces before creating an empty cache.
        # Warm declared acquisition/bootstrap without executing a graph action.
        nonce.write_text('bootstrap')
        acquisition = invoke(['build', '//:packages', '//:remote_bootstrap', '--jobs=4', '--spawn_strategy=linux-sandbox',
                              '--disk_cache=', '--remote_cache=', '--noshow_progress'], 'acquisition-bootstrap')
        (results / 'acquisition.json').write_text(json.dumps({'seconds': acquisition, 'scope': 'SDK, package extraction and runner bootstrap; separate from graph recovery'}) + '\n')
        if args.phase == 'producer':
            graph('seed', 0)
            suites('seed')
        else:
            seed = json.loads(args.seed_evidence.read_text())
            assert seed.get('slice', 'pipelines') == args.slice and seed['externalWorkspace'] != str(root), 'Use a relocated independent workspace'
            replay = graph('remote-recovery', count)
            assert replay['runnerSha256'] == seed['runnerSha256'] and replay['outputs'] == seed['outputs'], 'Independent recovery differs'
            if args.qualified_raw_results:
                qualified_raw_control('remote-recovery', replay)
            suites('remote-recovery')
            if args.edits:
                for case in ['body', 'api']:
                    for path, content in originals.items():
                        if (root / path).read_bytes() != content:
                            (root / path).write_bytes(content)
                    if case == 'body':
                        anchor = mutation['bodyAnchor'].encode()
                        assert originals[implementation].count(anchor) == 1
                        (root / implementation).write_bytes(originals[implementation].replace(anchor, anchor + b'\n            GC.KeepAlive("' + str(uuid.uuid4()).encode() + b'");'))
                    else:
                        declaration = ('\n        /// <summary>Independent recovery API control.</summary>\n        public const string RecoveryProbe = \"' + str(uuid.uuid4()) + '\";').encode()
                        for path, anchor in [(implementation, mutation['implementationAnchor'].encode()), (reference, mutation['referenceAnchor'].encode())]:
                            assert originals[path].count(anchor) == 1
                            (root / path).write_bytes(originals[path].replace(anchor, anchor + declaration))
                    # End the previous broker: unchanged projects must come from
                    # HTTP with empty local snapshots, including on edited builds.
                    stop(case + '-empty-local-cache')
                    edited = graph(case + '-remote', count - mutation['expectedMisses'][case])
                    assert edited['runnerSha256'] == seed['runnerSha256']
                    assert edited['outputs'][impl_dll] != seed['outputs'][impl_dll]
                    assert (edited['outputs'][ref_dll] == seed['outputs'][ref_dll]) == (case == 'body')
                    if args.qualified_raw_results:
                        qualified_raw_control(case + '-remote', edited)
                    else:
                        control = graph(case + '-native-control', 0, native=True)
                        assert control['outputs'] == edited['outputs'], 'Edited remote recovery differs from fresh native compilation'
                    suites(case + '-remote')
                for path, content in originals.items():
                    (root / path).write_bytes(content)
                stop('restore-empty-local-cache')
                restored = graph('restored-source-remote', count)
                assert restored['outputs'] == seed['outputs'], 'Restored original outputs differ from producer'
                if args.qualified_raw_results:
                    qualified_raw_control('restored-source', restored)
                suites('restored-source')
            if args.raw_control:
                raw_control(seed)
            if args.diagnostics:
                for path, content in originals.items():
                    if (root / path).read_bytes() != content:
                        (root / path).write_bytes(content)
                stop('diagnostic-empty-local-cache')
                diagnostic = graph('remote-recovery-diagnostic', count, profile=True)
                assert diagnostic['runnerSha256'] == seed['runnerSha256'] and diagnostic['outputs'] == seed['outputs']
                assert diagnostic['report']['remote']['downloads'] > 0 and diagnostic['report']['remote']['downloadBytes'] > 0
        print('PASS: independent ' + args.phase + ' project-cache controls', flush=True)
    finally:
        for path, content in originals.items():
            (root / path).write_bytes(content)
        if args.qualified_raw_results:
            for path, content in originals.items():
                (args.qualified_raw_results / 'raw-workspace' / path).write_bytes(content)
        generated.write_bytes(original_generated)
        build.write_bytes(original_build)
        bootstrap.unlink(missing_ok=True)
        nonce.unlink(missing_ok=True)
        subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
