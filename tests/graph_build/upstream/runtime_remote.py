"""Independent public-worker project-cache recovery for reviewed runtime slices.

Use a new producer/consumer output base and a separate consumer container. Whole
Bazel disk/remote action caches are disabled. Stop the producer before recovery.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    parser.add_argument('--slice', choices=['pipelines', 'loaded-common'], default='pipelines')
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'])
    parser.add_argument('--seed-evidence', type=Path, help='producer seed.json; required for consumer')
    parser.add_argument('--edits', action='store_true', help='consumer body/API remote recovery and fresh native controls')
    parser.add_argument('--diagnostics', action='store_true', help='separate profiled recovery for logical transfer counters; excluded from scored rows')
    parser.add_argument('--raw-control', action='store_true', help='fresh raw graph Restore/Build in the same consumer, after restoring original sources')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == (args.seed_evidence is not None)
    assert not (args.edits or args.diagnostics or args.raw_control) or args.phase == 'consumer'
    root, results, output_base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not output_base.exists() and not results.is_relative_to(root) and not root.is_relative_to(results)
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [(project, variant) for project, declaration in contract['Projects'].items()
             for variant in declaration.get('Configurations') or [declaration]]
    assert contract['SdkVersion'] == '10.0.400' and contract['Properties']['TargetOS'] == 'linux' and contract['Properties']['TargetArchitecture'] == 'arm64'
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for _, node in nodes)
    if args.slice == 'loaded-common':
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
    options = ['--jobs=4', '--strategy=MSBuildGraph=worker', '--spawn_strategy=linux-sandbox',
               '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--noshow_progress']
    rows = []
    generated, build = root / 'graph.generated.bzl', root / 'BUILD.bazel'
    original_generated, original_build = generated.read_bytes(), build.read_bytes()
    assert original_build.count(b'linux_worker=True') == 1
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
        configured = active_build.replace(b'linux_worker=True', b'linux_worker=False') if native else active_build
        if profile:
            configured = configured.replace(b'linux_worker=True', b'linux_worker=True,profile_build=True')
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
        # Warm declared acquisition/bootstrap without executing a graph action.
        nonce.write_text('bootstrap')
        acquisition = invoke(['build', '//:packages', '//:remote_bootstrap', '--jobs=4', '--spawn_strategy=linux-sandbox',
                              '--disk_cache=', '--remote_cache=', '--noshow_progress'], 'acquisition-bootstrap')
        (results / 'acquisition.json').write_text(json.dumps({'seconds': acquisition, 'scope': 'SDK, package extraction and runner bootstrap; separate from graph recovery'}) + '\n')
        if args.phase == 'producer':
            graph('seed', 0)
        else:
            seed = json.loads(args.seed_evidence.read_text())
            assert seed.get('slice', 'pipelines') == args.slice and seed['externalWorkspace'] != str(root), 'Use a relocated independent workspace'
            replay = graph('remote-recovery', count)
            assert replay['runnerSha256'] == seed['runnerSha256'] and replay['outputs'] == seed['outputs'], 'Independent recovery differs'
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
                    control = graph(case + '-native-control', 0, native=True)
                    assert control['outputs'] == edited['outputs'], 'Edited remote recovery differs from fresh native compilation'
                for path, content in originals.items():
                    (root / path).write_bytes(content)
                stop('restore-empty-local-cache')
                restored = graph('restored-source-remote', count)
                assert restored['outputs'] == seed['outputs'], 'Restored original outputs differ from producer'
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
        generated.write_bytes(original_generated)
        build.write_bytes(original_build)
        bootstrap.unlink(missing_ok=True)
        nonce.unlink(missing_ok=True)
        subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
