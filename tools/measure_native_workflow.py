"""Repeated complete native Build/Test versus ordinary MSBuild and VSTest."""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

from native_workflow import Workflow, ROOT, DOTNET_ROOT, BAZEL, bootstrap, remove_tree
from portable_cache import environment
from probe_native_serilog import hashes
from probe_native_workflow import fixture, TESTS
from probe_serilog_tests import PROJECT, ASSEMBLY, parse_results, REVISION
from protected_store import ProtectedStore

PROFILES = ('reuse', 'trusted-incremental')
CASES = ('cold', 'seeded', 'unchanged', 'body', 'test-edit', 'recovery')
BUDGET = dict(multiplier=1.25, additiveSeconds=0.250, cases=['unchanged', 'body', 'test-edit'])


def mutate(source, case):
    if case == 'body':
        p = source / 'src/Serilog/Log.cs'
        p.write_text(p.read_text().replace('public static class Log\n{', 'public static class Log\n{\n    static int NativeTimingProbe() => 42;'))
    elif case == 'test-edit':
        p = source / 'test/Serilog.ApprovalTests/ApiApprovalTests.cs'
        p.write_text(p.read_text().replace('public class ApiApprovalTests\n{', 'public class ApiApprovalTests\n{\n    static int NativeTimingProbe() => 42;'))


def measure(checkout, packages, output, repetitions=3, profiles=PROFILES):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    protocol = dict(repetitions=repetitions, profiles=profiles, cases=CASES, budget=BUDGET,
        revision=REVISION, scope='same-host macOS ARM64; preinstalled SDK/tools and restored package inputs; actual VSTest on every sample',
        excluded='initial tool bootstrap, source/package acquisition and Restore, diagnostic hash comparison after raw execution',
        included='SDK identity, native preparation and final lease validation, input/seed copies, Bazel startup/build/test and cache publication',
        raw='ordinary Build followed by direct VSTest, same Release/net10 and PathMap',
        cold='fresh source/build/preparation/Bazel state, warm OS/Nix/package acquisition caches',
        recovery='fresh source and Bazel/preparation state, only selected sealed project-cache bundles carried over',
        ordering='alternate raw/native order by repetition; profiles alternate order between repetitions',
        controller='reuse uses the one-shot CLI including Python startup; trusted-incremental retains a Python controller and protected-store cache; Bazel is retained within each sequence')
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2))
    report = dict(correctnessAccepted=False, protocol=protocol, samples=[], freshControls=[])
    def save(): (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    bootstrap()

    def raw(source, destination, expected):
        destination.mkdir()
        env = environment(DOTNET_ROOT, output / 'home', output, source)
        env.update(CI='true', DiffEngine_Disabled='true', MSBuildEnableWorkloadResolver='false', SHOULDLY_SOURCE_PATH_MAP=str(source) + '=/_/workspace')
        begin = time.perf_counter()
        commands = [[DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT, '-t:Build', '-p:Configuration=Release',
            '-p:TargetFramework=net10.0', '-p:PathMap=' + str(source) + '=/_/workspace', '-nodeReuse:false', '-nologo', '-v:normal'],
            [DOTNET_ROOT / 'dotnet', 'vstest', source / ASSEMBLY, '--logger:trx;LogFileName=results.trx', '--ResultsDirectory:' + str(destination)]]
        phases = []
        for index, command in enumerate(commands):
            start = time.perf_counter()
            result = subprocess.run(list(map(str, command)), cwd=source, env=env, capture_output=True, text=True, timeout=600)
            phases.append(time.perf_counter() - start)
            text = result.stdout + result.stderr; (destination / f'{index}.log').write_text(text)
            if result.returncode: raise AssertionError('raw command failed: ' + str(destination))
            if index == 0: compiles = sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in text.splitlines())
        seconds = time.perf_counter() - begin
        assert compiles == expected, ('raw work set', compiles, expected)
        test = parse_results(destination / 'results.trx'); assert test['passed'] == 1 and test['failed'] == 0
        runtime = hashes((source / ASSEMBLY).parent)
        diagnostic = runtime.pop('.msCoverageSourceRootsMapping_Serilog.ApprovalTests', None)
        return dict(seconds=seconds, phases=dict(build=phases[0], test=phases[1]), compiles=compiles, test=test,
                    runtimeHashes=runtime, rawOnlyCoverageDiagnostic=diagnostic)

    states = []
    def shutdown(state):
        if not (state / 'g').exists(): return
        result = subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
            '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', capture_output=True, text=True)
        if result.returncode: raise RuntimeError('Bazel shutdown failed: ' + result.stderr)

    try:
        for repetition in range(repetitions):
            for profile in (profiles if repetition % 2 == 0 else tuple(reversed(profiles))):
                base = output / f'{repetition}-{PROFILES.index(profile)}'; base.mkdir()
                declaration = base / 'tests.json'; declaration.write_text(json.dumps(TESTS))
                src = fixture(checkout, packages, base / 's')
                ordinary = fixture(checkout, packages, base / 'r')
                state = base / 'state'; states.append(state)
                store = ProtectedStore() if profile == 'trusted-incremental' else None
                workflow = Workflow(src, state, PROJECT, tests=TESTS, reuse=True, protected_store=store,
                                    incremental_sources=profile == 'trusted-incremental')
                for case in CASES:
                    if case in ('body', 'test-edit'):
                        mutate(src, case); mutate(ordinary, case)
                    if case == 'recovery':
                        recovered = fixture(checkout, packages, base / 's2')
                        fresh_raw = fixture(checkout, packages, base / 'r2')
                        for path in (recovered, fresh_raw): mutate(path, 'body'); mutate(path, 'test-edit')
                        next_state = base / 'state2'; next_state.mkdir()
                        for name in ('owner.json', 'cache.json'): shutil.copyfile(state / name, next_state / name)
                        pointer = json.loads((state / 'cache.json').read_text())['generation']
                        shutil.copytree(state / 'cache' / pointer, next_state / 'cache' / pointer)
                        shutdown(state)
                        # Prove recovery cannot read producer source, generated inputs,
                        # preparation state, local Bazel cache, or producer test outputs.
                        remove_tree(state); remove_tree(src); remove_tree(ordinary)
                        workflow = Workflow(recovered, next_state, PROJECT, tests=TESTS, reuse=True, protected_store=store,
                                            incremental_sources=profile == 'trusted-incremental')
                        src, ordinary, state = recovered, fresh_raw, next_state; states.append(state)
                    raw_compiles = 2 if case in ('cold', 'body', 'recovery') else 1 if case == 'test-edit' else 0
                    native_compiles = 2 if case in ('cold', 'body') else 1 if case == 'test-edit' else 0
                    def cli(label, reuse=True):
                        destination = base / label
                        command = [sys.executable, str(ROOT / 'tools/native_workflow.py'), '--workspace', str(src),
                            '--state', str(state), '--entry', PROJECT, '--tests', str(declaration), '--operation', 'test',
                            '--force-tests', '--output', str(destination)]
                        if reuse: command.append('--reuse')
                        begin = time.perf_counter()
                        process = subprocess.run(command, capture_output=True, text=True, timeout=900)
                        elapsed = time.perf_counter() - begin
                        (base / (label + '-cli.log')).write_text(process.stdout + process.stderr)
                        if process.returncode: raise AssertionError('native CLI failed: ' + str(destination))
                        result = json.loads((destination / 'report.json').read_text())
                        result['controllerSeconds'] = result['seconds']; result['seconds'] = elapsed
                        return result
                    def native():
                        return cli(case + '-native') if profile == 'reuse' else workflow.run(base / (case + '-native'), operation='test', force_tests=True)
                    if repetition % 2:
                        n = native(); r = raw(ordinary, base / (case + '-raw'), raw_compiles)
                    else:
                        r = raw(ordinary, base / (case + '-raw'), raw_compiles); n = native()
                    assert n['compiles'] == native_compiles, (profile, case, n['compiles'], native_compiles)
                    assert n['testActions'] == 1 and n['test']['successful'] == 1 and n['test']['skipped'] == 0
                    assert n['runtimeHashes'] == r['runtimeHashes'], (profile, case, 'runtime mismatch')
                    if case in ('seeded', 'unchanged'): assert n['preparation']['reused'], n['preparation']
                    if case == 'unchanged': assert n['buildActions'] == 0, 'unchanged outer action cache miss'
                    record = dict(profile=profile, repetition=repetition, case=case, native=n, raw=r)
                    report['samples'].append(record); save()
                    print(profile, repetition, case, round(n['seconds'], 3), round(r['seconds'], 3), n['compiles'], flush=True)
                if profile == 'reuse':
                    # Control: same final sources and warm build/test caches, but
                    # fresh export/preparation rather than retained native plans.
                    control = cli('fresh-control', reuse=False)
                    assert control['compiles'] == 0 and control['testActions'] == 1
                    assert control['runtimeHashes'] == report['samples'][-1]['raw']['runtimeHashes']
                    report['freshControls'].append(dict(repetition=repetition, result=control)); save()
                shutdown(state)
        report['summary'] = []
        for profile in profiles:
            for case in CASES:
                rows = [r for r in report['samples'] if r['profile'] == profile and r['case'] == case]
                n = statistics.median(r['native']['seconds'] for r in rows)
                r = statistics.median(r['raw']['seconds'] for r in rows)
                limit = r * BUDGET['multiplier'] + BUDGET['additiveSeconds']
                phases = {key: statistics.median(row['native']['phases'].get(key, 0) for row in rows)
                          for key in ('identity', 'prepare', 'stage', 'bazel', 'publish', 'leaseExit')}
                report['summary'].append(dict(profile=profile, case=case, nativeMedian=n, rawMedian=r, ratio=n / r,
                    nativeRange=[min(row['native']['seconds'] for row in rows), max(row['native']['seconds'] for row in rows)],
                    phaseMedians=phases, budgetSeconds=limit if case in BUDGET['cases'] else None,
                    targetMet=n <= limit if case in BUDGET['cases'] else None))
        report['correctnessAccepted'] = True
        report['performanceTargetMet'] = {profile: all(row['targetMet'] for row in report['summary']
            if row['profile'] == profile and row['targetMet'] is not None) for profile in profiles}
        report['freshControlMedian'] = statistics.median(row['result']['seconds'] for row in report['freshControls']) if report['freshControls'] else None
    except BaseException as error:
        report['failure'] = str(error); raise
    finally:
        for state in states:
            if state.exists(): shutdown(state)
        save()
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'packages', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--profiles', nargs='+', choices=PROFILES, default=PROFILES)
    a = p.parse_args()
    if a.repetitions < 1: p.error('repetitions must be positive')
    measure(a.source, a.packages, a.output, a.repetitions, tuple(a.profiles))
