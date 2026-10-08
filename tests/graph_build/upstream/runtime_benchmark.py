"""Paired public Bazel/raw graph timings for reviewed runtime test slices.

Inputs must first pass runtime_qualify.py. Large logs stay in the disposable
results directory; summary.json records only timings, counts and parity scope.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import threading
import zipfile
import xml.etree.ElementTree as ET

from runtime_root_properties import root_properties

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
    harness_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path, help='new owned directory, outside workspace')
    parser.add_argument('--output-base', type=Path, required=True, help='fresh base, or retained base with continuation/qualified raw results')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--body-only', action='store_true', help='score no-op/body/recovery only; retain strict compiler parity')
    parser.add_argument('--slice', choices=['pipelines-tests', 'collections', 'loaded-common', 'runtime-suites'], default='pipelines-tests')
    parser.add_argument('--continue-api-from', type=Path, help='completed no-op/body scorecard with retained raw state; record remaining cases separately')
    parser.add_argument('--qualified-raw-results', type=Path, help='completed full-source raw control for runtime-suites; reuse its warm outputs in place')
    parser.add_argument('--replay-omissions', action='store_true', help='compare all required products while checking explicit optional intermediates are absent; runtime-suites only')
    parser.add_argument('--evaluation-reuse', action='store_true', help='require retained evaluation for an explicit reviewed compiler-only inventory; runtime-suites only')
    parser.add_argument('--qualify-evaluation-only', action='store_true', help='profile broader retention correctness; report conservative extra compilations without matched-work scores')
    parser.add_argument('--edit-case', type=Path, help='reviewed runtime-suites edit descriptor; overrides the default Pipelines scenario')
    parser.add_argument('--reviewed-evaluation-inputs', type=Path, help='explicit reviewed compiler-only input list, including both edit sources')
    parser.add_argument('--reference-bindings', type=Path, help='qualify the reviewed full raw Build compiler/copy selections')
    parser.add_argument('--project-cache-url', help='recover baseline project snapshots through HTTP instead of a retained local worker')
    parser.add_argument('--compare-fresh-evaluation', action='store_true', help='pair retained edits with unique equivalent edits using evaluation_cache_mb=0')
    parser.add_argument('--failure-recovery', action='store_true', help='fail a compiler request, then compare a unique valid edit with raw MSBuild')
    parser.add_argument('--reseed-worker', action='store_true', help='with qualified raw outputs, require a fresh all-miss runner seed before scoring')
    parser.add_argument('--diagnostics', action='store_true', help='profile separate unique edits after the scored series')
    parser.add_argument('--trim-between-rows', action='store_true', help='Trim the owned Linux VM filesystem between observations, outside scored intervals; requires fstrim privileges')
    parser.add_argument('--host-space-path', type=Path, help='host bind mount to check for at least 4 GiB free before each invocation')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert args.samples > 0
    assert not args.body_only or (args.qualified_raw_results and not args.continue_api_from and not args.qualify_evaluation_only)
    assert not args.replay_omissions or args.qualified_raw_results
    assert not args.evaluation_reuse or args.qualified_raw_results
    assert not args.qualify_evaluation_only or (args.edit_case and args.evaluation_reuse and args.diagnostics and args.samples == 1 and not args.compare_fresh_evaluation and not args.failure_recovery)
    assert not args.edit_case or args.slice == 'runtime-suites'
    assert not args.reference_bindings or args.qualified_raw_results
    assert not args.reviewed_evaluation_inputs or args.evaluation_reuse
    assert not args.project_cache_url or args.qualified_raw_results
    assert not args.compare_fresh_evaluation or args.evaluation_reuse
    assert not args.reseed_worker or args.qualified_raw_results, 'Reseeding requires qualified complete-source raw outputs'
    assert not (args.continue_api_from and args.qualified_raw_results)
    assert bool(args.qualified_raw_results) == (args.slice == 'runtime-suites'), 'Larger timing requires the qualified full-source raw workspace'
    root, results = args.workspace.resolve(), args.results.resolve()
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert args.output_base.exists() == bool(args.continue_api_from or args.qualified_raw_results), 'Use a fresh base, or retain it with a qualified warm baseline'
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    dotnet = str(sdk / 'dotnet')
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    directories = {p for v in variants for p in v['OutputDirectories']}
    files = {p for v in variants for p in v.get('OutputFiles', [])}
    compiled = sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants)
    declared = set(contract['SharedInputs']) | {p for v in variants for p in v['Inputs']}
    if args.slice in ['collections', 'loaded-common', 'runtime-suites']:
        filename = {'collections': 'runtime_collections_edit.json', 'loaded-common': 'runtime_loaded_common_edit.json', 'runtime-suites': 'runtime_source_host_edit.json'}[args.slice]
        mutation = json.loads(Path(__file__).with_name(filename).read_text())
    else:
        mutation = dict(compiled=38, implementation=IMPLEMENTATION, reference=REFERENCE, implDll=IMPL_DLL, refDll=REF_DLL,
                        bodyAnchor='UseSynchronizationContext = useSynchronizationContext;',
                        implementationAnchor='public class PipeOptions\n    {', referenceAnchor='public partial class PipeOptions\n    {',
                        expectedMisses=dict(body=6, api=11), entries=['src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj'])
    implementation, reference = mutation['implementation'], mutation['reference']
    if args.edit_case:
        overrides = json.loads(args.edit_case.read_text())
        assert set(overrides) == {'implementation', 'reference', 'implDll', 'refDll', 'bodyAnchor', 'implementationAnchor', 'referenceAnchor', 'expectedMisses'}
        mutation.update(overrides)
        implementation, reference = mutation['implementation'], mutation['reference']
        assert all(type(value) is int and 0 < value <= compiled for value in mutation['expectedMisses'].values())
        assert set(mutation['expectedMisses']) == {'body', 'api'}
    reviewed_inputs = sorted([implementation, reference])
    if args.reviewed_evaluation_inputs:
        reviewed_inputs = json.loads(args.reviewed_evaluation_inputs.read_text())
        assert reviewed_inputs == sorted(set(reviewed_inputs)) and set(reviewed_inputs) <= declared
        assert {implementation, reference} <= set(reviewed_inputs)
    assert {implementation, reference} <= declared
    assert compiled == mutation['compiled'], 'Unexpected configured compilation scope'
    assert (contract.get('Entries') or [contract['Entry']]) == mutation['entries'], 'Unexpected roots'
    raw = results / 'raw-workspace'
    continuation = None
    qualified = None
    if args.qualified_raw_results:
        from runtime_full_source import normalize_reference_bindings, validate_raw_contract
        references = json.loads(args.reference_bindings.read_text()) if args.reference_bindings else None
        prior = args.qualified_raw_results.resolve()
        assert prior != results and not results.is_relative_to(prior) and not prior.is_relative_to(results)
        validate_raw_contract(contract, prior, allow_replay_omissions=args.replay_omissions,
                              evaluation_reuse_inputs=reviewed_inputs if args.evaluation_reuse else None,
                              reference_bindings=references)
        raw = prior / 'raw-workspace'
        raw_contract = json.loads((raw / 'graph.generated.json').read_text())
        comparison_contract = json.loads(json.dumps(contract))
        if references:
            normalize_reference_bindings(comparison_contract, raw_contract, references)
        if args.evaluation_reuse:
            comparison_contract.pop('EvaluationReuseInputs')
            raw_contract.pop('EvaluationReuseInputs', None)
            comparison_contract['Version'] = raw_contract['Version']
        if args.replay_omissions:
            for p in comparison_contract['Projects'].values():
                for v in [p] + p.get('Configurations', []):
                    v.pop('ReplayOmissions', None)
        assert raw_contract == comparison_contract
        assert (raw / '.qualification/Raw.dll').is_file()
        expansion_seconds = None
        qualified = dict(priorResults=str(prior), rawContractSha256=hashlib.sha256((raw / 'graph.generated.json').read_bytes()).hexdigest(),
                         contractSha256=hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest(),
                         reseedWorker=args.reseed_worker, interpretation='qualified full-source raw outputs; worker seed/restoration excluded from scored edits')
    elif args.continue_api_from:
        prior = args.continue_api_from.resolve()
        assert prior != results and not results.is_relative_to(prior)
        summary_path = prior / 'summary.json'
        previous = json.loads(summary_path.read_text())
        assert previous['slice'] == args.slice and previous['entries'] == mutation['entries']
        assert previous['sdkVersion'] == contract['SdkVersion'] and previous['bazelVersion'] == '9.3.0'
        assert previous['graphProjects'] == compiled and previous['cpus'] == 4 and previous['memoryGiB'] == 8
        for case in ['no-op', 'body']:
            completed = [row for row in previous['rows'] if row['case'] == case]
            assert len(completed) == args.samples and {row['sample'] for row in completed} == set(range(args.samples))
            assert sum(row['case'] == case + '-summary' for row in previous['rows']) == 1
            if case == 'body':
                assert all(row['projectMisses'] == mutation['expectedMisses']['body'] for row in completed)
        assert not any(row['case'] in ['api', 'api-summary', 'local-recovery'] for row in previous['rows']), 'Do not overwrite completed remaining cases'
        assert (prior / 'raw-workspace/graph.generated.json').read_bytes() == (root / 'graph.generated.json').read_bytes()
        shutil.copytree(prior / 'raw-workspace', raw, ignore=shutil.ignore_patterns('bazel-*', '.cache', '.cli'))
        expansion_seconds = None
        continuation = dict(priorResults=str(prior), priorSummarySha256=hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                            priorHarnessSha256=previous['harnessSha256'], interpretation='retained raw outputs/packages; restarted worker is reseeded before scoring; no cold/setup timing')
    else:
        shutil.copytree(root, raw, ignore=shutil.ignore_patterns('bazel-*', '.nuget', '.cache', '.cli'))
        expansion_seconds = expand_raw_packages(raw)
    packages = raw / '.nuget'
    config = raw / 'NuGet.Config'
    original_config = config.read_bytes() if config.exists() else None
    config.write_text('<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=dotnet,
                       NUGET_PACKAGES=str(packages), MSBUILDDISABLENODEREUSE='1', USE_BAZEL_VERSION='9.3.0')
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
    if args.project_cache_url:
        bazel += ['--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.project_cache_url]
    rows = []
    memory_samples = {}
    mode_counts = {}
    originals = {p: (root / p).read_bytes() for p in [implementation, reference]}
    assert all((raw / p).read_bytes() == content for p, content in originals.items())
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_bytes()
    build = root / 'BUILD.bazel'
    original_build = build.read_bytes()
    main_line = next(line for line in original_build.decode().splitlines() if line.startswith('app_graph(name="graph",'))
    def build_settings(fresh=False, profile=False):
        line = main_line
        if fresh:
            line = re.sub(r',\s*evaluation_cache_mb\s*=\s*\d+', '', line)
            assert line.count('linux_worker=True') == 1
            line = line.replace('linux_worker=True', 'linux_worker=True,evaluation_cache_mb=0')
        if profile:
            line = line.replace('linux_worker=True', 'linux_worker=True,profile_build=True')
        return original_build.decode().replace(main_line, line, 1)
    fresh_build_text = build_settings(fresh=True) if args.compare_fresh_evaluation else None
    nonce = root / 'force-recovery.txt'
    assert not nonce.exists()
    token = str(time.time_ns())

    def execute(command, label, cwd, expected_success=True):
        if args.host_space_path:
            disk = os.statvfs(args.host_space_path)
            if disk.f_bavail * disk.f_frsize < 4 * 1024**3 and args.trim_between_rows:
                subprocess.run(['fstrim', '/'], check=True, capture_output=True)
                # Thin backing storage can report reclamation after fstrim returns.
                for _ in range(5):
                    disk = os.statvfs(args.host_space_path)
                    if disk.f_bavail * disk.f_frsize >= 4 * 1024**3:
                        break
                    time.sleep(1)
            assert disk.f_bavail * disk.f_frsize >= 4 * 1024**3, 'Insufficient host disk headroom; preserve reports and reclaim disposable results'
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
            (results / 'memory-samples.json').write_text(json.dumps(memory_samples, indent=2) + '\n')
            if process.returncode and expected_success:
                raise subprocess.CalledProcessError(process.returncode, command)
            if not expected_success:
                assert process.returncode != 0, 'Invalid source unexpectedly succeeded'
        return elapsed

    def graph(label, expected_action=True):
        bep = results / (label + '.bep')
        elapsed = execute(bazel + ['--build_event_json_file=' + str(bep)], label, root)
        metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in bep.read_text().splitlines() if 'buildMetrics' in json.loads(line))
        actions = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraph')
        assert actions in [0, 1] if expected_action is None else actions == int(expected_action), (label, actions)
        preparations = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraphRestore')
        if label == 'graph-seed' or (args.reseed_worker and label == 'continued-graph-baseline'):
            assert preparations == int(bool(contract.get('Restore'))), (label, preparations)
        elif label == 'continued-graph-baseline':
            # Changing the reviewed contract can invalidate preparation once.
            # Baseline setup is unscored; every scored edit still requires reuse.
            assert preparations in [0, 1], (label, preparations)
        elif label.endswith('-diagnostic-graph') or 'diagnostic' not in label:
            assert preparations == 0, (label, preparations)
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        if expected_action is None and actions:
            assert (report['hits'], report['misses']) == (compiled, 0), (label, report)
        return elapsed, report

    def force_input(name):
        prefix, action = original_generated.decode().split('    msbuild_graph(\n')
        if args.diagnostics and contract.get('Restore'):
            # Compilation profiles reuse the unprofiled preparation. Profiling
            # Restore would invalidate its action and change the setup footprint.
            assert prefix.count('        profile_build = profile_build,') == 1
            prefix = prefix.replace('        profile_build = profile_build,', '        profile_build = False,', 1)
        assert action.count('        srcs = [') == 1
        return prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = [' + json.dumps(name) + ',', 1)

    def snapshot(workspace):
        paths = {workspace / p for p in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        return {str(p.relative_to(workspace)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
                for p in paths if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']
                and not (str(p.relative_to(workspace)).startswith('artifacts/obj/') and '/PreTrim/' in str(p.relative_to(workspace)))}

    from runtime_full_source import replay_omissions
    omitted = replay_omissions(contract) if args.replay_omissions else set()
    assert not {mutation['implDll'], mutation['refDll']} & omitted, 'Edit controls are required products'

    def compare():
        actual, expected = snapshot(root / 'bazel-bin/graph.graph/workspace'), snapshot(raw)
        if omitted:
            assert not omitted & actual.keys(), 'Optional intermediates were published'
            assert omitted <= expected.keys(), 'Candidate must be observed in the complete raw control'
            expected = {p: v for p, v in expected.items() if p not in omitted}
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
            anchor = mutation['bodyAnchor'].encode()
            assert originals[implementation].count(anchor) == 1
            replacement = anchor + b'\n            GC.KeepAlive("' + (token + '-' + str(sample)).encode() + b'");'
            changes = {implementation: originals[implementation].replace(anchor, replacement)}
        else:
            value = str(100000 + int(hashlib.sha256(token.encode()).hexdigest()[:6], 16) + sample).encode()
            declaration = b'\n        /// <summary>Qualification edit control.</summary>\n        public const int BenchmarkProbe = ' + value + b';'
            changes = {}
            for path, anchor in [(implementation, mutation['implementationAnchor'].encode()), (reference, mutation['referenceAnchor'].encode())]:
                assert originals[path].count(anchor) == 1
                changes[path] = originals[path].replace(anchor, anchor + declaration)
        for path, content in changes.items():
            (root / path).write_bytes(content)
            (raw / path).write_bytes(content)

    def record(row):
        row['observedFileModes'] = dict(mode_counts)
        rows.append(row)
        summary = dict(platform='linux-arm64', cpus=4, memoryGiB=8, msbuildNodes=4, graphProjects=compiled,
                       sdkVersion=contract['SdkVersion'], bazelVersion='9.3.0', slice=args.slice, entries=mutation['entries'], rawNamespace='same stable paths and isolation as graph',
                       harnessSha256=harness_sha256, packageExpansionSeconds=expansion_seconds,
                       continuation=continuation, qualifiedWarmBaseline=qualified, retainedEvaluation=args.evaluation_reuse,
                       editCase=str(args.edit_case) if args.edit_case else 'pipelines', reviewedEvaluationInputs=reviewed_inputs if args.evaluation_reuse else None,
                       referenceBindingsSha256=hashlib.sha256(args.reference_bindings.read_bytes()).hexdigest() if args.reference_bindings else None,
                       evaluationQualificationOnly=args.qualify_evaluation_only,
                       bodyOnly=args.body_only,
                       comparedFreshEvaluation=args.compare_fresh_evaluation,
                       omittedIntermediateFiles=len(omitted), trimBetweenRows=args.trim_between_rows, memorySamples=memory_samples, rows=rows)
        (results / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items()
                          if key not in ['runner', 'rawCompilerCalls', 'graphCompilerCalls']}), flush=True)
        if args.trim_between_rows:
            subprocess.run(['fstrim', '/'], check=True, capture_output=True)

    try:
        if continuation or qualified:
            assert len(mutation['entries']) > 1, 'Continuation currently requires the multi-root raw driver'
            assert (raw / '.qualification/Raw.dll').is_file()
            raw_command = raw_host + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
            seed_raw = execute(raw_command, 'continued-raw-baseline', raw)
            # Worker-local snapshots are process-owned and disappear on shutdown.
            # A unique declared input forces baseline execution even if Bazel's
            # whole-action cache already contains the original result.
            generated.write_text(force_input('force-recovery.txt'))
            nonce.write_text(token + '-continued-baseline')
            seed_graph, report = graph('continued-graph-baseline')
            assert report['hits'] + report['misses'] == compiled
            if qualified:
                expected_seed = (0, compiled) if args.reseed_worker else (compiled, 0)
                assert (report['hits'], report['misses']) == expected_seed, 'Expected fresh seed or retained qualified worker'
            assert report['operations'] is None and 'worker' not in report
            assert report['preparedRestore'] == bool(contract.get('Restore'))
            assert report['readOnlyPreparedPackages'] == bool(contract.get('Restore'))
            baseline = compare()
            generated.write_bytes(original_generated)
            nonce.unlink()
            record(dict(case='continued-baseline', rawSeconds=seed_raw, graphSeconds=seed_graph, projectHits=report['hits'], projectMisses=report['misses'],
                        comparedDllPdbResourceFiles=len(baseline), interpretation='baseline restoration; excluded from scored medians'))
        else:
            restore_command = raw_host + ['restore', stable + '/' + contract['Entry'], '--configfile', stable + '/NuGet.Config', '--source', stable + '/.package-source',
                               '--packages', stable + '/.nuget', '-p:NuGetAudit=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion']]
            restore_seconds = 0
            for index, entry in enumerate(mutation['entries']):
                command = restore_command + [f'-p:{k}={v}' for k, v in root_properties(contract, entry).items() if k.lower() != 'targetframework']
                command[command.index(stable + '/' + contract['Entry'])] = stable + '/' + entry
                restore_seconds += execute(command, 'raw-restore-' + str(index), raw)
            if len(mutation['entries']) > 1:
                driver = results / 'raw-driver'
                driver.mkdir()
                directory = Path(__file__).resolve().parent
                shutil.copyfile(directory / 'RuntimeRawGraph.cs.txt', driver / 'Program.cs')
                shutil.copyfile(directory / 'RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
                execute([dotnet, 'build', str(driver / 'Raw.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false'], 'raw-driver-build', results)
                shutil.copytree(driver / 'bin/Release/net10.0', raw / '.qualification')
                raw_command = raw_host + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build']
            seed_raw = execute(raw_command, 'raw-seed', raw)
            seed_graph, report = graph('graph-seed')
            assert report['hits'] == 0 and report['misses'] == compiled, report
            assert report['operations'] is None and 'worker' not in report
            assert report['preparedRestore'] == bool(contract.get('Restore'))
            assert report['readOnlyPreparedPackages'] == bool(contract.get('Restore'))
            baseline = compare()
            record(dict(case='setup', rawRestoreSeconds=restore_seconds, rawBuildSeconds=seed_raw, graphWorkflowSeconds=seed_graph,
                        comparedDllPdbResourceFiles=len(baseline), interpretation='setup includes Bazel bootstrap/package actions; not a scored cold row'))
        cases = ['no-op', 'body'] if args.body_only else ['no-op', 'body', 'api']
        for case in ([] if args.qualify_evaluation_only else ['api'] if continuation else cases):
            pairs = []
            fresh_pairs = []
            for sample in range(args.samples):
                if args.evaluation_reuse and case != 'no-op':
                    # A unique baseline primes retention even after worker restart
                    # or budget changes. Whole-action hits cannot establish state.
                    generated.write_text(force_input('force-recovery.txt'))
                    nonce.write_text(token + '-retained-' + case + '-' + str(sample))
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
                    assert report['misses'] == mutation['expectedMisses'][case], report
                    if args.evaluation_reuse:
                        assert report['evaluationState'] == dict(loaded=0, reused=len(variants), configuredProjects=len(variants)), report
                        assert report['buildNodeEvaluations'] == 0, report
                    assert outputs[mutation['implDll']] != baseline[mutation['implDll']]
                    assert (outputs[mutation['refDll']] == baseline[mutation['refDll']]) == (case == 'body')
                pairs.append(dict(rawSeconds=raw_seconds, graphSeconds=graph_seconds))
                record(dict(case=case, sample=sample, order='graph-first' if sample % 2 else 'raw-first',
                            **pairs[-1], projectHits=report['hits'] if case != 'no-op' else None,
                            projectMisses=report['misses'] if case != 'no-op' else None, wholeGraphActionHit=case == 'no-op',
                            comparedDllPdbResourceFiles=len(outputs), runner=report if case != 'no-op' else None))
                if args.compare_fresh_evaluation and case != 'no-op':
                    build.write_text(fresh_build_text)
                    edit(case, sample + 1000)
                    label = case + '-fresh-' + str(sample)
                    if sample % 2:
                        raw_seconds = execute(raw_command, label + '-raw', raw)
                        graph_seconds, report = graph(label + '-graph')
                    else:
                        graph_seconds, report = graph(label + '-graph')
                        raw_seconds = execute(raw_command, label + '-raw', raw)
                    assert report['evaluationState'] is None and report['misses'] == mutation['expectedMisses'][case], report
                    outputs = compare()
                    assert outputs[mutation['implDll']] != baseline[mutation['implDll']]
                    assert (outputs[mutation['refDll']] == baseline[mutation['refDll']]) == (case == 'body')
                    fresh_pairs.append(dict(rawSeconds=raw_seconds, graphSeconds=graph_seconds))
                    record(dict(case=case + '-fresh', sample=sample, order='raw-first' if sample % 2 else 'graph-first',
                                **fresh_pairs[-1], projectHits=report['hits'], projectMisses=report['misses'],
                                comparedDllPdbResourceFiles=len(outputs), runner=report))
                    build.write_bytes(original_build)
            record(dict(case=case + '-summary', rawMedianSeconds=statistics.median(p['rawSeconds'] for p in pairs),
                        graphMedianSeconds=statistics.median(p['graphSeconds'] for p in pairs),
                        rawRangeSeconds=[min(p['rawSeconds'] for p in pairs), max(p['rawSeconds'] for p in pairs)],
                        graphRangeSeconds=[min(p['graphSeconds'] for p in pairs), max(p['graphSeconds'] for p in pairs)]))
            if fresh_pairs:
                record(dict(case=case + '-fresh-summary', rawMedianSeconds=statistics.median(p['rawSeconds'] for p in fresh_pairs),
                            graphMedianSeconds=statistics.median(p['graphSeconds'] for p in fresh_pairs),
                            rawRangeSeconds=[min(p['rawSeconds'] for p in fresh_pairs), max(p['rawSeconds'] for p in fresh_pairs)],
                            graphRangeSeconds=[min(p['graphSeconds'] for p in fresh_pairs), max(p['graphSeconds'] for p in fresh_pairs)]))
        restore_sources()
        execute(raw_command, 'raw-original-restoration', raw)
        graph('graph-original-restoration', expected_action=None)
        assert compare() == baseline
        generated.write_text(force_input('force-recovery.txt'))
        for sample in range(0 if args.qualify_evaluation_only else args.samples):
            nonce.write_text(token + '-' + str(sample))
            seconds, report = graph('local-recovery-' + str(sample))
            assert report['hits'] == compiled and report['misses'] == 0, report
            assert compare() == baseline
            record(dict(case='local-recovery', sample=sample, graphSeconds=seconds, projectHits=compiled, projectMisses=0, runner=report))
        if args.failure_recovery:
            generated.write_bytes(original_generated)
            (root / implementation).write_bytes(originals[implementation] + b'\ninvalid qualification source\n')
            execute(bazel, 'expected-compiler-failure', root, expected_success=False)
            failure = (results / 'expected-compiler-failure.log').read_text()
            assert any(Path(implementation).name + '(' in line and 'error CS' in line for line in failure.splitlines()), 'Expected a source compiler error'
            edit('body', args.samples + 20)
            raw_seconds = execute(raw_command, 'failure-recovery-raw', raw)
            graph_seconds, report = graph('failure-recovery-graph')
            assert report['misses'] == mutation['expectedMisses']['body'], report
            if args.evaluation_reuse:
                assert report['evaluationState'] == dict(loaded=len(variants), reused=0, configuredProjects=len(variants)), report
            outputs = compare()
            record(dict(case='failure-recovery', rawSeconds=raw_seconds, graphSeconds=graph_seconds,
                        projectHits=report['hits'], projectMisses=report['misses'],
                        comparedDllPdbResourceFiles=len(outputs), runner=report))
            restore_sources()
            execute(raw_command, 'raw-failure-original-restoration', raw)
            graph('graph-failure-original-restoration', expected_action=None)
            assert compare() == baseline
        if args.diagnostics:
            generated.write_bytes(original_generated)
            assert b'profile_build = False' in original_generated, 'Regenerate with the profiling-capable ProjectSync first'
            build.write_text(build_settings(profile=True))
            reader = results / 'binlog-reader'
            reader.mkdir()
            fixture = ROOT / 'tests/runtime'
            shutil.copyfile(fixture / 'Inventory.csproj.txt', reader / 'Reader.csproj')
            shutil.copyfile(fixture / 'RawTimingLog.cs.txt', reader / 'Program.cs')
            execute([dotnet, 'build', str(reader / 'Reader.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false'], 'reader-build', results)
            def compilation(path):
                details = json.loads(subprocess.check_output([dotnet, str(reader / 'bin/Release/net10.0/Reader.dll'), str(path)], env=environment, text=True))
                return details['compiled']
            edits = ['body'] if args.body_only else ['body', 'api']
            controls = [(case, False) for case in edits]
            if args.compare_fresh_evaluation:
                controls += [(case, True) for case in edits]
            for sample, (case, fresh) in enumerate(controls, start=args.samples):
                build.write_text(build_settings(fresh=fresh, profile=True))
                label = case + ('-fresh' if fresh else '') + '-diagnostic'
                if args.evaluation_reuse:
                    generated.write_text(force_input('force-recovery.txt'))
                    nonce.write_text(token + '-diagnostic-baseline-' + str(sample))
                restore_sources()
                execute(raw_command, label + '-raw-baseline', raw)
                graph(label + '-graph-baseline', expected_action=None)
                edit(case, sample)
                diagnostic = raw / '.qualification'
                diagnostic.mkdir(exist_ok=True)
                raw_binlog = diagnostic / (label + '.binlog')
                binlog = stable + '/.qualification/' + raw_binlog.name
                logging = [binlog] if len(mutation['entries']) > 1 else ['-bl:' + binlog + ';ProjectImports=None']
                raw_seconds = execute(raw_command + logging, label + '-raw', raw)
                shutil.copyfile(raw_binlog, results / (label + '-raw.binlog'))
                seconds, report = graph(label + '-graph')
                assert report['operations'] and report['worker']
                assert report['buildNodeEvaluations'] == 0, report
                if args.evaluation_reuse:
                    expected_state = None if fresh else dict(loaded=0, reused=len(variants), configuredProjects=len(variants))
                    assert report['evaluationState'] == expected_state, report
                shutil.copyfile(root / 'bazel-bin/graph.graph/report.binlog', results / (label + '-graph.binlog'))
                outputs = compare()
                assert outputs[mutation['implDll']] != baseline[mutation['implDll']]
                assert (outputs[mutation['refDll']] == baseline[mutation['refDll']]) == (case == 'body')
                raw_compilers = compilation(results / (label + '-raw.binlog'))
                graph_compilers = compilation(results / (label + '-graph.binlog'))
                expected = mutation['expectedMisses'][case]
                assert len(raw_compilers) == expected, (case, raw_compilers)
                assert len(graph_compilers) == (report['misses'] if args.qualify_evaluation_only else expected), (case, graph_compilers)
                def compiler_set(calls):
                    return Counter((call['project'], call['framework'], call['task']) for call in calls)
                equivalent = compiler_set(raw_compilers) == compiler_set(graph_compilers)
                if args.qualify_evaluation_only:
                    assert not (compiler_set(raw_compilers) - compiler_set(graph_compilers)), (case, raw_compilers, graph_compilers)
                else:
                    assert equivalent, (case, raw_compilers, graph_compilers)
                record(dict(case=label, graphSeconds=seconds, rawSeconds=raw_seconds, compilerWorkEquivalent=equivalent,
                            comparedDllPdbResourceFiles=len(outputs), implementationDigest=outputs[mutation['implDll']]['sha256'], referenceDigest=outputs[mutation['refDll']]['sha256'],
                            runner=report, rawCompilerCalls=raw_compilers,
                            graphCompilerCalls=graph_compilers, interpretation='profiled correctness control; excluded from scored medians'))
            restore_sources()
            build.write_bytes(original_build)
            execute(raw_command, 'raw-diagnostic-original-restoration', raw)
            graph('graph-diagnostic-original-restoration', expected_action=None)
            assert compare() == baseline
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
