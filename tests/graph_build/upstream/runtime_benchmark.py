"""Paired public Bazel/raw graph timings for the pinned Pipelines test slice.

Inputs must first pass runtime_qualify.py. Large logs stay in the disposable
results directory; summary.json records only timings, counts and parity scope.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import threading
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
IMPLEMENTATION = 'src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'
REFERENCE = 'src/libraries/System.IO.Pipelines/ref/System.IO.Pipelines.cs'
IMPL_DLL = 'artifacts/bin/System.IO.Pipelines/Release/net10.0/System.IO.Pipelines.dll'
REF_DLL = 'artifacts/bin/System.IO.Pipelines/ref/Release/net10.0/System.IO.Pipelines.dll'


def expand_raw_packages(raw):
    packages = raw / '.nuget'
    # Start from the same declared archives, including package SDK bootstrap.
    # Expansion is setup, reported separately from ordinary raw Restore/Build.
    expansion_start = time.monotonic()
    for archive in sorted((raw / '.package-source').glob('*.nupkg')):
        data = archive.read_bytes()
        with zipfile.ZipFile(archive) as package:
            metadata = ET.fromstring(package.read(next(n for n in package.namelist() if n.endswith('.nuspec'))))
            def field(name):
                return next(i.text for i in metadata.iter() if i.tag.split('}')[-1] == name).lower()
            identity, version = field('id'), field('version')
            assert all(value and '/' not in value and '\\' not in value and '..' not in value for value in [identity, version])
            destination = packages / identity / version
            destination.mkdir(parents=True, exist_ok=False)
            package.extractall(destination)
        name = identity + '.' + version + '.nupkg'
        shutil.copyfile(archive, destination / name)
        digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
        (destination / (name + '.sha512')).write_text(digest)
        (destination / '.nupkg.metadata').write_text(json.dumps(dict(version=2, contentHash=digest, source=str(raw / '.package-source'))))
    return time.monotonic() - expansion_start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path, help='new owned directory, outside workspace')
    parser.add_argument('--output-base', type=Path, required=True, help='unused Bazel output base')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--diagnostics', action='store_true', help='profile separate unique edits after the scored series')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert args.samples > 0
    root, results = args.workspace.resolve(), args.results.resolve()
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert not args.output_base.exists(), 'Use a new owned output base'
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    dotnet = str(sdk / 'dotnet')
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    directories = {p for v in variants for p in v['OutputDirectories']}
    files = {p for v in variants for p in v.get('OutputFiles', [])}
    compiled = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants)
    declared = set(contract['SharedInputs']) | {p for v in variants for p in v['Inputs']}
    assert {IMPLEMENTATION, REFERENCE} <= declared
    assert compiled == 38, 'This mutation contract qualifies only the reviewed test slice'
    raw = results / 'raw-workspace'
    shutil.copytree(root, raw, ignore=shutil.ignore_patterns('bazel-*', '.nuget', '.cache', '.cli'))
    packages = raw / '.nuget'
    expansion_seconds = expand_raw_packages(raw)
    config = raw / 'NuGet.Config'
    original_config = config.read_bytes() if config.exists() else None
    config.write_text('<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=dotnet,
                       NUGET_PACKAGES=str(packages), MSBUILDDISABLENODEREUSE='1', USE_BAZEL_VERSION='9.2.0')
    environment.pop('RULES_MSBUILD_GRAPH_PROFILE', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    stable = '/__rules_msbuild_graph/output/workspace'
    stable_sdk = '/__rules_msbuild_graph/sdk'
    scratch = results / 'raw-scratch'
    scratch.mkdir()
    raw_host = ['bash', str(ROOT / 'tests/graph_build/upstream/runtime_raw.sh'), str(sdk), str(raw), str(scratch)]
    properties = [f'-p:{key}={value}' for key, value in contract['Properties'].items()]
    common = ['-p:UseSharedCompilation=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion'],
              '-p:PathMap=' + stable + '=/_/workspace%2C' + stable_sdk + '=/_/sdk']
    raw_command = raw_host + ['msbuild', stable + '/' + contract['Entry'], '-graphBuild', '-m:4', '-t:Build', '-nologo', *common, *properties]
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()),
             'build', '//:graph', '--jobs=4', '--strategy=MSBuildGraph=worker', '--spawn_strategy=linux-sandbox',
             '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--noshow_progress']
    rows = []
    memory_samples = {}
    mode_counts = {}
    originals = {p: (root / p).read_bytes() for p in [IMPLEMENTATION, REFERENCE]}
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_bytes()
    build = root / 'BUILD.bazel'
    original_build = build.read_bytes()
    nonce = root / 'force-recovery.txt'
    assert not nonce.exists()
    token = str(time.time_ns())

    def execute(command, label, cwd):
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
            samples = []
            stopped = threading.Event()
            def sample_memory():
                while True:
                    memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
                    samples.append((memory['MemTotal'], memory['MemAvailable']))
                    if stopped.wait(0.25):
                        return
            sampler = threading.Thread(target=sample_memory)
            sampler.start()
            try:
                process.wait()
                elapsed = time.monotonic() - start
            finally:
                stopped.set()
                sampler.join()
            total = samples[-1][0]
            minimum_available = min(available for _, available in samples)
            memory_samples[label] = dict(vmTotalKiB=total, minimumAvailableKiB=minimum_available,
                                         maximumUsedKiB=total - minimum_available, samplingIntervalSeconds=0.25)
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
        return elapsed

    def graph(label, expected_action=True):
        bep = results / (label + '.bep')
        elapsed = execute(bazel + ['--build_event_json_file=' + str(bep)], label, root)
        metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in bep.read_text().splitlines() if 'buildMetrics' in json.loads(line))
        actions = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraph')
        assert actions in [0, 1] if expected_action is None else actions == int(expected_action), (label, actions)
        preparations = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraphRestore')
        if label == 'graph-seed':
            assert preparations == int(bool(contract.get('Restore'))), (label, preparations)
        elif 'diagnostic' not in label:
            assert preparations == 0, (label, preparations)
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        if expected_action is None and actions:
            assert (report['hits'], report['misses']) == (compiled, 0), (label, report)
        return elapsed, report

    def force_input(name):
        prefix, action = original_generated.decode().split('    msbuild_graph(\n')
        assert action.count('        srcs = [') == 1
        return prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = [' + json.dumps(name) + ',', 1)

    def snapshot(workspace):
        paths = {workspace / p for p in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        return {str(p.relative_to(workspace)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
                for p in paths if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']
                and not (str(p.relative_to(workspace)).startswith('artifacts/obj/') and '/PreTrim/' in str(p.relative_to(workspace)))}

    def compare():
        actual, expected = snapshot(root / 'bazel-bin/graph.graph/workspace'), snapshot(raw)
        # Bazel freezes declared tree artifacts to 0555 after the action. Raw
        # outputs remain writable. Record both modes; compare bytes without
        # altering either filesystem or treating freezing as a compiler mismatch.
        mode_counts.update(graph=dict(Counter(oct(v['mode']) for v in actual.values())),
                           raw=dict(Counter(oct(v['mode']) for v in expected.values())))
        actual_bytes = {p: v['sha256'] for p, v in actual.items()}
        expected_bytes = {p: v['sha256'] for p, v in expected.items()}
        if actual_bytes != expected_bytes:
            differences = {p: {'graph': actual.get(p), 'raw': expected.get(p)} for p in actual.keys() | expected.keys() if actual_bytes.get(p) != expected_bytes.get(p)}
            (results / 'differences.json').write_text(json.dumps(differences, indent=2))
            raise AssertionError('DLL/PDB/resource parity failed; see differences.json')
        return actual

    def restore_sources():
        for path, content in originals.items():
            for workspace in [root, raw]:
                source = workspace / path
                if source.read_bytes() != content:
                    source.write_bytes(content)

    def edit(case, sample):
        restore_sources()
        if case == 'body':
            anchor = b'UseSynchronizationContext = useSynchronizationContext;'
            assert originals[IMPLEMENTATION].count(anchor) == 1
            replacement = anchor + b'\n            GC.KeepAlive("' + (token + '-' + str(sample)).encode() + b'");'
            changes = {IMPLEMENTATION: originals[IMPLEMENTATION].replace(anchor, replacement)}
        else:
            value = str(100000 + int(hashlib.sha256(token.encode()).hexdigest()[:6], 16) + sample).encode()
            declaration = b'\n        /// <summary>Qualification edit control.</summary>\n        public const int BenchmarkProbe = ' + value + b';'
            changes = {}
            for path, anchor in [(IMPLEMENTATION, b'public class PipeOptions\n    {'), (REFERENCE, b'public partial class PipeOptions\n    {')]:
                assert originals[path].count(anchor) == 1
                changes[path] = originals[path].replace(anchor, anchor + declaration)
        for path, content in changes.items():
            (root / path).write_bytes(content)
            (raw / path).write_bytes(content)

    def record(row):
        row['observedFileModes'] = dict(mode_counts)
        rows.append(row)
        summary = dict(platform='linux-arm64', cpus=4, memoryGiB=8, msbuildNodes=4, graphProjects=compiled,
                       sdkVersion=contract['SdkVersion'], bazelVersion='9.2.0', rawNamespace='same stable paths and isolation as graph',
                       harnessSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), packageExpansionSeconds=expansion_seconds,
                       memorySamples=memory_samples, rows=rows)
        (results / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(row), flush=True)

    try:
        restore_command = raw_host + ['restore', stable + '/' + contract['Entry'], '--configfile', stable + '/NuGet.Config', '--source', stable + '/.package-source',
                           '--packages', stable + '/.nuget', '-p:NuGetAudit=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion']]
        restore_command += [f'-p:{k}={v}' for k, v in contract['Properties'].items() if k.lower() != 'targetframework']
        restore_seconds = execute(restore_command, 'raw-restore', raw)
        seed_raw = execute(raw_command, 'raw-seed', raw)
        seed_graph, report = graph('graph-seed')
        assert report['hits'] == 0 and report['misses'] == compiled, report
        assert report['operations'] is None and 'worker' not in report
        assert report['preparedRestore'] == bool(contract.get('Restore'))
        assert report['readOnlyPreparedPackages'] == bool(contract.get('Restore'))
        baseline = compare()
        record(dict(case='setup', rawRestoreSeconds=restore_seconds, rawBuildSeconds=seed_raw, graphWorkflowSeconds=seed_graph,
                    comparedDllPdbResourceFiles=len(baseline), interpretation='setup includes Bazel bootstrap/package actions; not a scored cold row'))
        for case in ['no-op', 'body', 'api']:
            pairs = []
            for sample in range(args.samples):
                restore_sources()
                graph(case + '-baseline-' + str(sample), expected_action=None)
                execute(raw_command, case + '-raw-baseline-' + str(sample), raw)
                if case != 'no-op':
                    edit(case, sample)
                label = case + '-' + str(sample)
                if sample % 2:
                    graph_seconds, report = graph(label + '-graph', case != 'no-op')
                    raw_seconds = execute(raw_command, label + '-raw', raw)
                else:
                    raw_seconds = execute(raw_command, label + '-raw', raw)
                    graph_seconds, report = graph(label + '-graph', case != 'no-op')
                outputs = compare()
                if case != 'no-op':
                    assert report['misses'] == (6 if case == 'body' else 11), report
                    assert outputs[IMPL_DLL] != baseline[IMPL_DLL]
                    assert (outputs[REF_DLL] == baseline[REF_DLL]) == (case == 'body')
                pairs.append(dict(rawSeconds=raw_seconds, graphSeconds=graph_seconds))
                record(dict(case=case, sample=sample, order='graph-first' if sample % 2 else 'raw-first',
                            **pairs[-1], projectHits=report['hits'] if case != 'no-op' else None,
                            projectMisses=report['misses'] if case != 'no-op' else None, wholeGraphActionHit=case == 'no-op',
                            comparedDllPdbResourceFiles=len(outputs), runner=report if case != 'no-op' else None))
            record(dict(case=case + '-summary', rawMedianSeconds=statistics.median(p['rawSeconds'] for p in pairs),
                        graphMedianSeconds=statistics.median(p['graphSeconds'] for p in pairs),
                        rawRangeSeconds=[min(p['rawSeconds'] for p in pairs), max(p['rawSeconds'] for p in pairs)],
                        graphRangeSeconds=[min(p['graphSeconds'] for p in pairs), max(p['graphSeconds'] for p in pairs)]))
        restore_sources()
        execute(raw_command, 'raw-original-restoration', raw)
        graph('graph-original-restoration', expected_action=None)
        assert compare() == baseline
        generated.write_text(force_input('force-recovery.txt'))
        for sample in range(args.samples):
            nonce.write_text(token + '-' + str(sample))
            seconds, report = graph('local-recovery-' + str(sample))
            assert report['hits'] == compiled and report['misses'] == 0, report
            assert compare() == baseline
            record(dict(case='local-recovery', sample=sample, graphSeconds=seconds, projectHits=compiled, projectMisses=0, runner=report))
        if args.diagnostics:
            generated.write_bytes(original_generated)
            assert b'profile_build = False' in original_generated, 'Regenerate with the profiling-capable ProjectSync first'
            build.write_text(original_build.decode().replace('linux_worker=True', 'linux_worker=True,profile_build=True'))
            reader = results / 'binlog-reader'
            reader.mkdir()
            fixture = ROOT / 'tests/explicit_msbuild/runtime'
            shutil.copyfile(fixture / 'Inventory.csproj.txt', reader / 'Reader.csproj')
            shutil.copyfile(fixture / 'RawTimingLog.cs.txt', reader / 'Program.cs')
            execute([dotnet, 'build', str(reader / 'Reader.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false'], 'reader-build', results)
            def compilation(path):
                details = json.loads(subprocess.check_output([dotnet, str(reader / 'bin/Release/net10.0/Reader.dll'), str(path)], env=environment, text=True))
                return details['compiled']
            for sample, case in enumerate(['body', 'api'], start=args.samples):
                restore_sources()
                execute(raw_command, case + '-diagnostic-raw-baseline', raw)
                graph(case + '-diagnostic-graph-baseline', expected_action=None)
                edit(case, sample)
                diagnostic = raw / '.qualification'
                diagnostic.mkdir(exist_ok=True)
                raw_binlog = diagnostic / (case + '.binlog')
                execute(raw_command + ['-bl:' + stable + '/.qualification/' + raw_binlog.name + ';ProjectImports=None'], case + '-diagnostic-raw', raw)
                shutil.copyfile(raw_binlog, results / (case + '-diagnostic-raw.binlog'))
                seconds, report = graph(case + '-diagnostic-graph')
                assert report['operations'] and report['worker']
                shutil.copyfile(root / 'bazel-bin/graph.graph/report.binlog', results / (case + '-diagnostic-graph.binlog'))
                compare()
                raw_compilers = compilation(results / (case + '-diagnostic-raw.binlog'))
                graph_compilers = compilation(results / (case + '-diagnostic-graph.binlog'))
                expected = 6 if case == 'body' else 11
                assert len(raw_compilers) == len(graph_compilers) == expected, (case, raw_compilers, graph_compilers)
                record(dict(case=case + '-diagnostic', graphSeconds=seconds, runner=report, rawCompilerCalls=raw_compilers,
                            graphCompilerCalls=graph_compilers, interpretation='profiled; excluded from scored medians'))
    finally:
        restore_sources()
        generated.write_bytes(original_generated)
        build.write_bytes(original_build)
        nonce.unlink(missing_ok=True)
        if original_config is None:
            config.unlink(missing_ok=True)
        else:
            config.write_bytes(original_config)
        subprocess.run(bazel[:2] + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
