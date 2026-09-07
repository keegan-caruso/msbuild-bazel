#!/usr/bin/env python3
"""Repeated R04 ordinary-MSBuild versus Bazel Build/Test measurements.

This is a bounded, local measurement harness for the pinned
Serilog.ApprovalTests Release/net10.0 slice.  It deliberately reports descriptive
measurements without a performance pass: numeric budgets have not been set.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import time
import zipfile

from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_bazel import json_stream
from probe_serilog_tests import REVISION, PROJECT, ASSEMBLY, APPROVED, FACT, parse_results


CASES = ('fresh', 'unchanged', 'sourceEdited', 'recovered')
SYSTEMS = ('ordinary', 'bazel')
SOURCE_FILE = 'test/Serilog.ApprovalTests/ApiApprovalTests.cs'
MUTATION_MARKER = '    private const string PerformanceProbe = "edited-v1";\n\n'
EXPECTED_COMPILERS = {'fresh': 2, 'unchanged': 0, 'sourceEdited': 1, 'recovered': 2}
EXPECTED_BAZEL_EXECUTIONS = {
    'fresh': ['Serilog', 'Serilog.ApprovalTests'],
    'unchanged': [],
    'sourceEdited': ['Serilog.ApprovalTests'],
    'recovered': [],
}


def build_schedule(repetitions):
    """Interleave system order for every independently initialized case."""
    schedule = []
    for repetition in range(1, repetitions + 1):
        for index, case in enumerate(CASES):
            order = SYSTEMS if (repetition + index) % 2 else tuple(reversed(SYSTEMS))
            schedule.append(dict(repetition=repetition, case=case, systems=list(order)))
    return schedule


def parse_msbuild_csc_count(log):
    """Count executed compiler tasks, excluding incrementally skipped targets."""
    return len(re.findall(r'Task "Csc"\s+\(TaskId:\d+\)', log))


def parse_msbuild_project_visits(log):
    marker = 'Project Performance Summary:'
    if marker not in log:
        return []
    section = log.split(marker, 1)[1].split('Target Performance Summary:', 1)[0]
    visits = []
    for line in section.splitlines():
        match = re.match(r'^\s*[\d.]+\s+ms\s+(.+?)\s+(\d+)\s+calls?\s*$', line)
        if match:
            visits.append(dict(project=match.group(1), calls=int(match.group(2))))
    return visits


def parse_msbuild_target_visits(log):
    marker = 'Target Performance Summary:'
    if marker not in log:
        return []
    section = log.split(marker, 1)[1].split('Task Performance Summary:', 1)[0]
    visits = []
    for line in section.splitlines():
        match = re.match(r'^\s*[\d.]+\s+ms\s+(.+?)\s+(\d+)\s+calls?\s*$', line)
        if match:
            visits.append(dict(target=match.group(1), calls=int(match.group(2))))
    return visits


def classify_bazel_actions(records, graph):
    nodes = {node['id']: Path(node['project']).stem for node in graph['nodes']}
    builds, tests = [], []
    for record in records:
        if record.get('mnemonic') == 'MsbuildProject':
            identity = record['targetLabel'].split(':node_')[-1]
            builds.append(dict(nodeId=identity, project=nodes[identity],
                cacheHit=record.get('cacheHit', False), runner=record.get('runner')))
        elif record.get('mnemonic') == 'TestRunner':
            tests.append(dict(cacheHit=record.get('cacheHit', False), runner=record.get('runner')))
    return builds, tests


def summarize_samples(samples):
    result = {}
    for case in CASES:
        result[case] = {}
        for system in SYSTEMS:
            selected = [sample for sample in samples if sample.get('status') == 'passed'
                        and sample['case'] == case and sample['system'] == system]
            metrics = {}
            for field in ('comparisonSeconds', 'fullWorkflowSeconds', 'comparisonPeakAggregateRssBytes'):
                values = [sample[field] for sample in selected if sample[field] is not None]
                if values:
                    metrics[field] = dict(median=statistics.median(values), minimum=min(values), maximum=max(values))
            phase_names = sorted({name for sample in selected for name in sample['phases']})
            phases = {}
            for phase in phase_names:
                values = [sample['phases'][phase]['wallSeconds'] for sample in selected if phase in sample['phases']]
                phases[phase] = dict(median=statistics.median(values), minimum=min(values), maximum=max(values))
            result[case][system] = dict(sampleCount=len(selected), metrics=metrics, phases=phases)
    return result


def _tail(path, limit=5000):
    if not path.is_file():
        return ''
    text = path.read_text(errors='replace')
    return text[-limit:]


class Harness:
    def __init__(self, source, packages, output, repetitions, host_note, bazel_mode):
        self.source = Path(source).resolve()
        self.packages = Path(packages).resolve()
        self.output = Path(output).resolve()
        self.repetitions = repetitions
        self.host_note = host_note
        self.bazel_mode = bazel_mode
        self.dotnet = DOTNET_ROOT / 'dotnet'
        self.strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
        self.archive = b''
        self.report = {}

    def environment(self, workspace, sample):
        return dict(os.environ, DOTNET_ROOT=str(DOTNET_ROOT),
            NUGET_PACKAGES=str(workspace / '.nuget/packages'),
            DOTNET_CLI_HOME=str(Path(sample['directory']) / 'cli-home'), DOTNET_NOLOGO='1',
            DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_MULTILEVEL_LOOKUP='0',
            MSBUILDDISABLENODEREUSE='1', DiffEngine_Disabled='true', CI='true')

    def run_process(self, sample, phase, command, cwd, *, timeout=1200, expected=0, measured=True):
        command = list(map(str, command))
        log = Path(sample['directory']) / (phase + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        started_utc = datetime.now(timezone.utc).isoformat()
        record = dict(command=command, cwd=str(cwd), returncode=None,
            wallSeconds=None, processTreePeakBytes=None,
            memoryStatus='unmeasured for R04; process sampling would perturb short no-op timings',
            startedUtc=started_utc, log=log.relative_to(self.output).as_posix(),
            includedInComparison=measured, status='starting')
        sample['phases'][phase] = record
        started = time.perf_counter()
        timed_out = False
        try:
            with log.open('w') as stream:
                process = subprocess.Popen(command, cwd=cwd, env=self.environment(Path(cwd), sample),
                    text=True, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                record['status'] = 'running'
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        returncode = process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        returncode = process.wait()
        except BaseException as error:
            record.update(status='failed-to-run', wallSeconds=time.perf_counter() - started,
                          error=dict(type=type(error).__name__, message=str(error)))
            raise
        elapsed = time.perf_counter() - started
        record.update(returncode=returncode, wallSeconds=elapsed, status='finished')
        if timed_out:
            raise TimeoutError(phase + ' timed out; see ' + str(log))
        if (expected == 0 and returncode != 0) or (expected != 0 and returncode == 0):
            raise RuntimeError(phase + ' unexpected exit ' + str(returncode) + '\n' + _tail(log))
        return log.read_text(errors='replace')

    def timed_operation(self, sample, phase, operation, *, measured=False):
        started = time.perf_counter()
        operation()
        sample['phases'][phase] = dict(wallSeconds=time.perf_counter() - started,
            processTreePeakBytes=None, memoryStatus='in-process setup operation; RSS not sampled',
            includedInComparison=measured)

    def remove_tree(self, path):
        path = Path(path)
        if not path.exists():
            return
        for directory, _, _ in os.walk(path, followlinks=False):
            candidate = Path(directory)
            if not candidate.is_symlink():
                candidate.chmod(candidate.stat().st_mode | 0o700)
        shutil.rmtree(path)

    def materialize(self, sample, workspace, prefix=''):
        label = prefix + '-' if prefix else ''
        self.timed_operation(sample, label + 'sourceExtraction', lambda: self._extract(workspace))
        self.timed_operation(sample, label + 'packageCopy',
            lambda: shutil.copytree(self.packages, workspace / '.nuget/packages'))
        sample['cacheState'][label + 'copiedPackageDirectory'] = self.directory_state(workspace / '.nuget/packages')

    def _extract(self, workspace):
        with tarfile.open(fileobj=io.BytesIO(self.archive)) as contents:
            contents.extractall(workspace, filter='data')

    def mutate_source(self, workspace):
        path = workspace / SOURCE_FILE
        original = path.read_text()
        needle = 'public class ApiApprovalTests\n{\n'
        if needle not in original or MUTATION_MARKER in original:
            raise AssertionError('unexpected approval test source shape')
        path.write_text(original.replace(needle, needle + MUTATION_MARKER, 1))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def restore(self, sample, workspace, phase='restore', measured=False):
        return self.run_process(sample, phase, [self.dotnet, 'msbuild', PROJECT, '-t:Restore',
            '-p:Configuration=Release', '-p:TargetFramework=net10.0', '-m:2',
            '-nodeReuse:false', '-nologo'], workspace, measured=measured)

    def ordinary_build(self, sample, workspace, phase, *, measured):
        binlog = Path(sample['directory']) / (phase + '.binlog')
        log = self.run_process(sample, phase, [self.dotnet, 'msbuild', PROJECT, '-t:Build',
            '-p:Configuration=Release', '-p:TargetFramework=net10.0',
            '-m:2', '-nodeReuse:false', '-nologo',
            '-verbosity:diagnostic', '-bl:' + str(binlog)], workspace, measured=measured)
        return dict(compilerInvocations=parse_msbuild_csc_count(log),
            projectVisits=parse_msbuild_project_visits(log),
            targetVisits=parse_msbuild_target_visits(log),
            binlog=binlog.relative_to(self.output).as_posix())

    def ordinary_test(self, sample, workspace, phase='test'):
        results = Path(sample['directory']) / (phase + '-results')
        results.mkdir()
        self.run_process(sample, phase, [self.dotnet, 'vstest', workspace / ASSEMBLY,
            '--Tests:' + FACT, '--logger:trx;LogFileName=results.trx',
            '--ResultsDirectory:' + str(results)], workspace, measured=True)
        parsed = parse_results(results / 'results.trx')
        if parsed['passed'] != 1 or parsed['failed'] != 0:
            raise AssertionError('ordinary VSTest did not pass exactly one expected Fact')
        return parsed

    def export_prepare(self, sample, workspace, generated, phase_prefix='', *, measured=True):
        prefix = phase_prefix + '-' if phase_prefix else ''
        directory = Path(sample['directory'])
        manifest = directory / (prefix + 'manifest.json')
        request = directory / (prefix + 'request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100',
            packageRoot=str(workspace / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties={
                'Configuration': 'Release', 'TargetFramework': 'net10.0'})],
            output=str(manifest))))
        export_phase = prefix + 'export'
        self.run_process(sample, export_phase,
            [self.dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll',
             '--request', request], workspace, measured=measured)
        graph_file = directory / (prefix + 'prepared-graph.json')
        prepare_phase = prefix + 'preparation'
        self.run_process(sample, prepare_phase, [sys.executable, Path(__file__).resolve(),
            '--internal-prepare', '--source', workspace, '--manifest', manifest,
            '--generated', generated, '--graph-output', graph_file,
            '--measurement-output', directory], ROOT, measured=measured)
        graph = json.loads(graph_file.read_text())
        if len(graph['nodes']) != 2 or {node['targetFramework'] for node in graph['nodes']} != {'net10.0'}:
            raise AssertionError('selected two-project net10.0 graph required')
        return graph

    def bazel_command(self, state, verb, targets, execution, profile, force_test=False):
        command = [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(state / 'output-base'),
            '--output_user_root=' + str(state / 'bazel-user'), verb, *targets,
            '--repository_cache=' + str(self.output / 'acquisition/repository-cache'),
            '--disk_cache=' + str(state / 'disk-cache'), '--spawn_strategy=' + self.strategy,
            '--strategy=MsbuildProject=' + self.strategy, '--strategy=TestRunner=' + self.strategy,
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no',
            '--remote_download_outputs=all', '--execution_log_json_file=' + str(execution),
            '--profile=' + str(profile), *(['--nocache_test_results', '--test_output=errors'] if force_test else [])]
        if self.bazel_mode == 'server':
            command.remove('--batch')
            command.insert(1, '--max_idle_secs=120')
        return command

    def shutdown_bazel(self, sample, state, phase='bazelShutdown'):
        if self.bazel_mode == 'batch':
            return
        command = [BAZEL, '--max_idle_secs=120', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(state / 'output-base'),
            '--output_user_root=' + str(state / 'bazel-user'), 'shutdown']
        self.run_process(sample, phase, command, ROOT, timeout=60, measured=False)

    def profile_summary(self, path):
        with gzip.open(path, 'rt') as stream:
            trace = json.load(stream)
        events = [event for event in trace['traceEvents'] if event.get('ph') == 'X' and 'dur' in event]
        named = {}
        for name in ('buildTargets', 'runAnalysisAndExecutionPhase', 'prepareForExecution'):
            durations = [event['dur'] / 1e6 for event in events if event.get('name') == name]
            named[name] = max(durations) if durations else None
        longest = sorted(events, key=lambda event: event['dur'], reverse=True)[:15]
        return dict(namedEventSeconds=named, eventsMayOverlap=True,
            longestEvents=[dict(name=event.get('name'), category=event.get('cat'),
                seconds=event['dur'] / 1e6) for event in longest])

    def bazel_invoke(self, sample, state, generated, graph, phase, verb, *, force_test=False, measured=True):
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
        targets = (['//:test_' + entry['id']] if verb == 'test' else
                   ['//:node_' + node['id'] for node in sorted(graph['nodes'], key=lambda item: item['id'])])
        execution = Path(sample['directory']) / (phase + '-execution.json')
        profile = Path(sample['directory']) / (phase + '-profile.json.gz')
        log = self.run_process(sample, phase,
            self.bazel_command(state, verb, targets, execution, profile, force_test),
            generated, measured=measured)
        records = list(json_stream(execution))
        builds, tests = classify_bazel_actions(records, graph)
        for action in builds:
            diagnostic = generated / ('bazel-bin/node_' + action['nodeId'] + '.diagnostics')
            if diagnostic.is_dir():
                retained = Path(sample['directory']) / 'action-evidence' / phase / action['nodeId']
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(diagnostic, retained)
                action['diagnostic'] = retained.relative_to(self.output).as_posix()
            if action['cacheHit']:
                continue
            if action['runner'] != self.strategy:
                raise AssertionError('noncached build action did not use the required native sandbox')
            detail = json.loads((diagnostic / 'action.json').read_text())
            action['compiledProjects'] = detail['compiledProjects']
            if detail['compiledProjects'] != [action['project']]:
                raise AssertionError('isolated action compiled an unexpected project set: ' + str(detail['compiledProjects']))
        timing = re.search(r'Elapsed time: ([\d.]+)s, Critical Path: ([\d.]+)s', log)
        return dict(buildActions=builds, testActions=tests,
            requestedTargets=targets,
            bazelReportedSeconds=float(timing.group(1)) if timing else None,
            criticalPathSeconds=float(timing.group(2)) if timing else None,
            executionLog=execution.relative_to(self.output).as_posix(),
            profile=profile.relative_to(self.output).as_posix(),
            profileSummary=self.profile_summary(profile))

    def bundle_inventory(self, generated, graph):
        inventory = {}
        for node in graph['nodes']:
            bundle = generated / ('bazel-bin/node_' + node['id'] + '.bundle')
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    logical = node['id'] + '/' + path.relative_to(bundle).as_posix()
                    inventory[logical] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        executable=bool(path.stat().st_mode & 0o111))
        return inventory

    def bazel_test_result(self, sample, generated, graph, expected_data_hashes):
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
        target = 'test_' + entry['id']
        source = generated / 'bazel-testlogs' / target
        retained = Path(sample['directory']) / 'test-evidence'
        shutil.copytree(source, retained, symlinks=False)
        for archive in retained.rglob('outputs.zip'):
            with zipfile.ZipFile(archive) as contents:
                contents.extractall(archive.parent / 'unpacked')
        trx = list(retained.rglob('*.trx'))
        runners = list(retained.rglob('report.json'))
        if len(trx) != 1 or len(runners) != 1:
            raise AssertionError('exactly one TRX and one runner report required')
        parsed = parse_results(trx[0])
        runner = json.loads(runners[0].read_text())
        if (parsed['passed'] != 1 or parsed['failed'] != 0 or runner.get('total') != 1 or
            runner.get('successful') != 1 or runner.get('failed') != 0 or
            runner.get('skipped') != 0 or runner.get('passed') is not True or runner.get('exitCode') != 0):
            raise AssertionError('Bazel did not run exactly one passing expected Fact')
        if runner.get('buildOrRestoreInvoked') is not False:
            raise AssertionError('Bazel test runner invoked build or restore')
        command = runner.get('command', [])
        if len(command) < 3 or Path(command[0]).name != 'dotnet' or Path(command[1]).name != 'vstest.console.dll':
            raise AssertionError('Bazel test action did not directly invoke SDK VSTest')
        if runner.get('dataHashes') != expected_data_hashes:
            raise AssertionError('Bazel test runner data hashes differ from declared inputs')
        return dict(result=parsed, runnerReport=runner,
            evidence=retained.relative_to(self.output).as_posix())

    def validate_bazel_work(self, case, build, test, materialized_projects):
        requested = ['Serilog', 'Serilog.ApprovalTests']
        if len(build['requestedTargets']) != 2 or any(not target.startswith('//:node_') for target in build['requestedTargets']):
            raise AssertionError(case + ' did not explicitly request both configured node targets')
        if sorted(materialized_projects) != requested:
            raise AssertionError(case + ' did not materialize both requested project bundles')
        executed = sorted(action['project'] for action in build['buildActions'] if not action['cacheHit'])
        if executed != sorted(EXPECTED_BAZEL_EXECUTIONS[case]):
            raise AssertionError(case + ' Bazel executed projects differ: ' + str(executed))
        if any(action['runner'] != self.strategy for action in build['buildActions'] if not action['cacheHit']):
            raise AssertionError(case + ' Bazel build did not use the required native sandbox')
        if any(not action['cacheHit'] for action in test['buildActions']):
            raise AssertionError(case + ' test phase unexpectedly rebuilt a project')
        recorded = {action['project'] for action in build['buildActions']}
        omitted = sorted(set(requested) - recorded)
        local_hits = sorted(action['project'] for action in build['buildActions']
                            if action['cacheHit'] and action['runner'] != 'disk cache hit')
        expected_reuse = {
            'fresh': [], 'unchanged': requested,
            'sourceEdited': ['Serilog'], 'recovered': requested,
        }[case]
        if sorted(set(omitted) | set(local_hits) |
                  {action['project'] for action in build['buildActions'] if action['runner'] == 'disk cache hit'}) != expected_reuse:
            raise AssertionError(case + ' Bazel reuse partition differs')
        build['materializedProjects'] = sorted(materialized_projects)
        build['materializedWithoutExecutionRecord'] = omitted
        build['recordedLocalCacheHitProjects'] = local_hits
        build['omissionMeaning'] = 'materialized output with no execution-log record; not inferred as a cache hit'
        actual_tests = [action for action in test['testActions'] if not action['cacheHit']]
        if len(test['testActions']) != 1 or len(actual_tests) != 1 or actual_tests[0]['runner'] != self.strategy:
            raise AssertionError(case + ' must execute one native uncached TestRunner')
        if case == 'recovered':
            hits = sorted(action['project'] for action in build['buildActions'] if action['cacheHit'])
            if hits != ['Serilog', 'Serilog.ApprovalTests'] or any(action['runner'] != 'disk cache hit' for action in build['buildActions']):
                raise AssertionError('recovery must obtain both project bundles from disk cache')

    def execute_ordinary(self, sample):
        root = Path(sample['directory']) / 'state'
        workspace = root / 'source'
        root.mkdir()
        self.materialize(sample, workspace)
        self.restore(sample, workspace)
        sample['cacheState'].update(outputsPresentBeforeWarmup=(workspace / ASSEMBLY).is_file(),
            msbuildResultCacheConfigured=False)
        warmup = None
        baseline_hash = None
        if sample['case'] != 'fresh':
            warmup = self.ordinary_build(sample, workspace, 'warmupBuild', measured=False)
            if warmup['compilerInvocations'] != 2:
                raise AssertionError('ordinary independent baseline did not compile both projects')
            baseline_hash = hashlib.sha256((workspace / ASSEMBLY).read_bytes()).hexdigest()
        if sample['case'] == 'sourceEdited':
            sample['editedSourceSha256'] = self.mutate_source(workspace)
        elif sample['case'] == 'recovered':
            for relative in ('src/Serilog/bin', 'src/Serilog/obj/Release',
                             'test/Serilog.ApprovalTests/bin', 'test/Serilog.ApprovalTests/obj/Release'):
                self.remove_tree(workspace / relative)
            sample['cacheState']['outputsDeletedBeforeBuild'] = True
        sample['cacheState']['outputsPresentBeforeMeasuredBuild'] = (workspace / ASSEMBLY).is_file()
        build = self.ordinary_build(sample, workspace, 'build', measured=True)
        expected = EXPECTED_COMPILERS[sample['case']]
        if build['compilerInvocations'] != expected:
            raise AssertionError(f"{sample['case']} ordinary compiler count {build['compilerInvocations']}, expected {expected}")
        assembly_hash = hashlib.sha256((workspace / ASSEMBLY).read_bytes()).hexdigest()
        if sample['case'] == 'sourceEdited' and assembly_hash == baseline_hash:
            raise AssertionError('source edit did not change the test assembly')
        test = self.ordinary_test(sample, workspace)
        sample.update(workset=dict(expectedCompilerInvocations=expected, **build),
            warmupWorkset=warmup, testResult=test, assemblySha256=assembly_hash)

    def execute_bazel(self, sample):
        state = Path(sample['directory']) / 'state'
        producer, generated = state / 'producer-source', state / 'producer-generated'
        state.mkdir()
        self.materialize(sample, producer)
        self.restore(sample, producer)
        sample['cacheState'].update(outputBasePresentBeforeWarmup=(state / 'output-base').exists(),
            diskCacheBeforeWarmup=self.directory_state(state / 'disk-cache'))
        graph = self.export_prepare(sample, producer, generated,
            'baseline' if sample['case'] != 'fresh' else '', measured=sample['case'] == 'fresh')
        warmup = None
        baseline_inventory = None
        baseline_assembly = None
        expected_data_hashes = None
        if sample['case'] != 'fresh':
            warmup = self.bazel_invoke(sample, state, generated, graph, 'warmupBuild', 'build', measured=False)
            warm_executed = sorted(action['project'] for action in warmup['buildActions'] if not action['cacheHit'])
            if warm_executed != ['Serilog', 'Serilog.ApprovalTests']:
                raise AssertionError('Bazel independent baseline did not execute both projects')
            baseline_inventory = self.bundle_inventory(generated, graph)
            entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
            baseline_assembly = baseline_inventory[entry['id'] + '/artifacts/' + ASSEMBLY]['sha256']
            self.remove_tree(generated)
        if sample['case'] == 'sourceEdited':
            sample['editedSourceSha256'] = self.mutate_source(producer)
            graph = self.export_prepare(sample, producer, generated)
        elif sample['case'] == 'unchanged':
            graph = self.export_prepare(sample, producer, generated)
        elif sample['case'] == 'recovered':
            self.shutdown_bazel(sample, state, 'producerServerShutdown')
            self.remove_tree(state / 'output-base')
            self.remove_tree(producer)
            relocated_source, generated = state / 'relocated-source', state / 'relocated-generated'
            self.materialize(sample, relocated_source, 'relocated')
            self.restore(sample, relocated_source, 'relocatedRestore')
            graph = self.export_prepare(sample, relocated_source, generated)
            expected_data_hashes = {relative: hashlib.sha256((relocated_source / relative).read_bytes()).hexdigest()
                for relative in (SOURCE_FILE, APPROVED)}
            self.remove_tree(relocated_source)
            absent = all(not path.exists() for path in
                (producer, state / 'producer-generated', state / 'output-base', relocated_source))
            sample['cacheState']['producerStateAbsentBeforeBuild'] = absent
            sample['cacheState']['outputBaseAbsentBeforeBuild'] = not (state / 'output-base').exists()
            sample['cacheState']['diskCacheRetained'] = (state / 'disk-cache').is_dir()
            if not absent:
                raise AssertionError('producer state survived recovery setup')
        if expected_data_hashes is None:
            expected_data_hashes = {relative: hashlib.sha256((producer / relative).read_bytes()).hexdigest()
                for relative in (SOURCE_FILE, APPROVED)}
        sample['cacheState'].update(outputBaseBeforeMeasuredBuild=self.directory_state(state / 'output-base'),
            diskCacheBeforeMeasuredBuild=self.directory_state(state / 'disk-cache'))
        build = self.bazel_invoke(sample, state, generated, graph, 'build', 'build')
        inventory = self.bundle_inventory(generated, graph)
        materialized_projects = [Path(node['project']).stem for node in graph['nodes']
                                 if (generated / ('bazel-bin/node_' + node['id'] + '.bundle')).is_dir()]
        test = self.bazel_invoke(sample, state, generated, graph, 'test', 'test', force_test=True)
        self.validate_bazel_work(sample['case'], build, test, materialized_projects)
        test_result = self.bazel_test_result(sample, generated, graph, expected_data_hashes)
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
        assembly_hash = inventory[entry['id'] + '/artifacts/' + ASSEMBLY]['sha256']
        if sample['case'] == 'sourceEdited' and assembly_hash == baseline_assembly:
            raise AssertionError('source edit did not change the Bazel test bundle assembly')
        if sample['case'] == 'recovered' and inventory != baseline_inventory:
            raise AssertionError('recovered bundle inventory differs from its independent baseline')
        if sample['case'] == 'recovered':
            sample['baselineBundleFiles'] = baseline_inventory
            sample['recoveredBundleMatchesBaseline'] = True
        sample.update(workset=dict(expectedExecutedProjects=EXPECTED_BAZEL_EXECUTIONS[sample['case']],
            build=build, test=test), warmupWorkset=warmup, testResult=test_result,
            assemblySha256=assembly_hash, bundleFiles=inventory)

    def finish_sample(self, sample):
        comparison = [phase for phase in sample['phases'].values() if phase.get('includedInComparison')]
        sample['comparisonSeconds'] = sum(phase['wallSeconds'] for phase in comparison)
        sample['fullWorkflowSeconds'] = sum(phase['wallSeconds'] for phase in sample['phases'].values())
        sample['comparisonPeakAggregateRssBytes'] = None
        sample['status'] = 'passed'
        sample['hostStateAfter'] = self.sample_host_state()

    def directory_state(self, path):
        path = Path(path)
        files = [item for item in path.rglob('*') if item.is_file()] if path.is_dir() else []
        return dict(exists=path.exists(), fileCount=len(files), totalFileBytes=sum(item.stat().st_size for item in files))

    def sample_host_state(self):
        return dict(timestampUtc=datetime.now(timezone.utc).isoformat(), loadAverage=list(os.getloadavg()),
            freeWorkspaceBytes=shutil.disk_usage(self.output).free,
            compilerServerProcesses=self.compiler_server_processes())

    def compiler_server_processes(self):
        result = subprocess.run(['ps', '-axo', 'pid=,lstart=,command='], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if result.returncode:
            return []
        return [line.strip() for line in result.stdout.splitlines()
                if 'VBCSCompiler' in line and 'ps -axo' not in line]

    def host_identity(self):
        def output(command):
            return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
        memory = None
        if platform.system() == 'Darwin':
            try:
                memory = int(output(['sysctl', '-n', 'hw.memsize']))
            except (OSError, subprocess.SubprocessError, ValueError):
                pass
        return dict(platform=platform.platform(), system=platform.system(), release=platform.release(),
            architecture=platform.machine(), processor=platform.processor(), logicalCpuCount=os.cpu_count(),
            physicalMemoryBytes=memory, hostNote=self.host_note,
            sdkRoot=str(DOTNET_ROOT), dotnetInfo=output([self.dotnet, '--info']),
            bazelVersion=output([BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
                '--output_user_root=' + str(self.output / 'host-bazel-user'), 'version', '--gnu_format']))

    def initialize_report(self):
        self.report = dict(schemaVersion=1, scope='R04-Serilog-ApprovalTests-comparative-measurement',
            status='running', accepted=False, performanceQualified=False, budgets=None,
            budgetStatus='unset before measurement; descriptive results only', revision=REVISION,
            sourceArchiveSha256=hashlib.sha256(self.archive).hexdigest(),
            adapterRevision=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
            adapterWorktreeStatus=subprocess.check_output(['git', '-C', str(ROOT), 'status', '--short'], text=True).splitlines(),
            packageDirectory=dict(path=str(self.packages), **self.directory_state(self.packages)),
            project=PROJECT, configuration='Release', targetFramework='net10.0', fact=FACT,
            repetitions=self.repetitions, schedule=build_schedule(self.repetitions),
            host=self.host_identity(), repositoryToolchainPins=json.loads((ROOT / 'scripts/toolchains.json').read_text()),
            cacheAndProcessPolicy=dict(remoteCaching=False, remoteExecution=False,
                bazelMode=self.bazel_mode, bazelDefaultMode='server',
                bazelServerScope='one server per independent case/system sample; shut down after sample',
                bazelRcFiles='Nix system rc retained for its pinned JDK; home/workspace rc disabled', jobs=2,
                msbuildNodeReuse=False,
                csharpSharedCompilation='SDK default enabled; compiler-server reuse is possible and sampled in host state',
                dotnetCliHome='separate directory per system/case/repetition sample',
                packageSource='pre-acquired pinned package directory copied per independent sample',
                repositoryCache='pre-acquired once; shared read/write repository cache; action disk caches remain per sample/case',
                testPolicy='ordinary direct VSTest and Bazel --nocache_test_results; one actual Fact every sample'),
            timingMethod=dict(clock='time.perf_counter', processTreeMemory=None,
                memoryStatus='unmeasured in R04 to avoid process-sampling distortion; aggregate process-tree/server RSS remains an R09 gate',
                comparison='ordinary Build+VSTest; Bazel export+preparation+Build+forced VSTest action',
                excluded='source extraction, package copy, restore, independent baseline warm-up, server shutdown, assertions and evidence copying',
                profileCaveat='Bazel trace events overlap and are reported without summing nested events'),
            cases=dict(fresh='empty outputs; empty Bazel output base/action disk cache',
                unchanged='independently warmed unmodified baseline',
                sourceEdited='independently warmed unmodified baseline followed by an observable test-source assembly edit',
                recovered='ordinary output-deleted rebuild; Bazel producer-free relocated recovery with fresh output base and retained action disk cache'),
            crossSystemComparability=dict(fresh=dict(comparable=True), unchanged=dict(comparable=True),
                sourceEdited=dict(comparable=True), recovered=dict(comparable=False,
                    reason='ordinary is a same-path output-deleted rebuild while Bazel is producer-free relocated disk-cache recovery; no ratio is valid')),
            samples=[], summaries={})

    def preflight(self):
        sample = dict(directory=str(self.output / 'acquisition'), phases={}, cacheState={},
                      case='acquisition', system='bazel', repetition=0)
        self.report['acquisition'] = sample
        directory = Path(sample['directory'])
        directory.mkdir()
        source, generated = directory / 'source', directory / 'generated'
        self.materialize(sample, source)
        self.restore(sample, source)
        graph = self.export_prepare(sample, source, generated, measured=False)
        entry = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + PROJECT)
        execution, profile = directory / 'fetch-execution.json', directory / 'fetch-profile.json.gz'
        try:
            targets = ['//:node_' + node['id'] for node in graph['nodes']]
            targets.extend(['//:test_' + entry['id'], '--nobuild'])
            self.run_process(sample, 'bazelRepositoryAcquisition', self.bazel_command(directory,
                'build', targets, execution, profile),
                generated, measured=False)
        finally:
            self.shutdown_bazel(sample, directory)
        sample['status'] = 'passed'

    def run(self):
        if self.output.exists():
            raise FileExistsError(self.output)
        if subprocess.check_output(['git', '-C', str(self.source), 'rev-parse', 'HEAD'], text=True).strip() != REVISION:
            raise ValueError('wrong Serilog revision')
        self.archive = subprocess.check_output(['git', '-C', str(self.source), 'archive', REVISION])
        self.output.mkdir(parents=True)
        self.initialize_report()
        stage = 'exporter bootstrap'
        bootstrap = dict(directory=str(self.output / 'bootstrap'), phases={})
        self.report['bootstrap'] = bootstrap
        Path(bootstrap['directory']).mkdir()
        try:
            self.run_process(bootstrap, 'exporterBuild', [self.dotnet, 'build', ROOT / 'tools/GraphExport',
                '-c', 'Release', '-nodeReuse:false', '--nologo'], ROOT, measured=False)
            stage = 'repository acquisition'
            self.preflight()
            for slot in self.report['schedule']:
                for system in slot['systems']:
                    stage = f"repetition {slot['repetition']} {slot['case']} {system}"
                    directory = self.output / 'samples' / f"r{slot['repetition']:02d}-{slot['case']}-{system}"
                    sample = dict(repetition=slot['repetition'], case=slot['case'], system=system,
                        directory=str(directory), status='running', phases={}, cacheState=dict(
                            independentCaseState=True, remoteCacheEnabled=False, remoteExecutionEnabled=False),
                        crossSystemComparable=slot['case'] != 'recovered',
                        hostStateBefore=self.sample_host_state())
                    directory.mkdir(parents=True)
                    self.report['samples'].append(sample)
                    self.write_report()
                    try:
                        (self.execute_ordinary if system == 'ordinary' else self.execute_bazel)(sample)
                        self.finish_sample(sample)
                    except BaseException as error:
                        sample['status'] = 'failed'
                        sample['error'] = dict(type=type(error).__name__, message=str(error))
                        raise
                    finally:
                        if system == 'bazel':
                            try:
                                self.shutdown_bazel(sample, directory / 'state')
                            except BaseException as shutdown_error:
                                sample['shutdownError'] = dict(type=type(shutdown_error).__name__, message=str(shutdown_error))
                                if sample.get('status') != 'failed':
                                    sample['status'] = 'failed'
                                    sample['error'] = sample['shutdownError']
                                    raise
                        self.write_report()
            self.report['summaries'] = summarize_samples(self.report['samples'])
            self.report['status'] = 'accepted-correctness-and-worksets'
            self.report['accepted'] = True
        except BaseException as error:
            self.report['status'] = 'failed'
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.write_report()
        return self.report

    def write_report(self):
        (self.output / 'report.json').write_text(json.dumps(self.report, indent=2) + '\n')


def internal_prepare(source, manifest, generated, graph_output, measurement_output):
    source, manifest, generated = map(lambda value: Path(value).resolve(), (source, manifest, generated))
    exported = json.loads(manifest.read_text())
    entry = next(node for node in exported['nodes'] if node['project'] == 'workspace/' + PROJECT)
    tests = [dict(node=entry['id'], data=[SOURCE_FILE, APPROVED], expectedTests=[FACT])]
    environment = dict(os.environ, DOTNET_ROOT=str(DOTNET_ROOT),
        NUGET_PACKAGES=str(source / '.nuget/packages'), DOTNET_CLI_HOME=str(Path(measurement_output) / 'cli-home'),
        DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_MULTILEVEL_LOOKUP='0',
        MSBUILDDISABLENODEREUSE='1', DiffEngine_Disabled='true', CI='true')
    graph = prepare(source, manifest, generated, environment=environment, tests=tests)
    Path(graph_output).write_text(json.dumps(graph, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--packages', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--host-note', default='exclusive local measurement window; operator must confirm competing workload state')
    parser.add_argument('--bazel-mode', choices=('server', 'batch'),
                        default=os.environ.get('SPIKE_BAZEL_MODE', 'server'))
    parser.add_argument('--describe-plan', action='store_true')
    parser.add_argument('--internal-prepare', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--manifest', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--generated', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--graph-output', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--measurement-output', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.describe_plan:
        print(json.dumps(dict(cases=list(CASES), systems=list(SYSTEMS),
            repetitions=args.repetitions, schedule=build_schedule(args.repetitions),
            bazelMode=args.bazel_mode, performanceQualified=False, budgets=None), indent=2))
        return
    if args.internal_prepare:
        required = (args.source, args.manifest, args.generated, args.graph_output, args.measurement_output)
        if any(value is None for value in required):
            parser.error('internal preparation arguments are incomplete')
        internal_prepare(*required)
        return
    if args.repetitions < 3:
        parser.error('--repetitions must be at least 3')
    if any(value is None for value in (args.source, args.packages, args.output)):
        parser.error('--source, --packages and --output are required')
    Harness(args.source, args.packages, args.output, args.repetitions, args.host_note, args.bazel_mode).run()


if __name__ == '__main__':
    main()
