"""Descriptive, paired calibration of fresh and reused preparation for RUL-7.

Inputs are already restored and tools prebuilt. Output/state must be outside the
controller checkout. This reports calibration only, never a performance pass.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

from preparation_reuse import ROOT, prepared_view, fresh_view, tool_identity
from preparation_identity import tree_snapshot
from discovery_contract import SDK


def summarize(samples):
    result = {}
    for mode in ('fresh', 'reuse'):
        values = [s['seconds'] for s in samples if s['mode'] == mode and s['status'] == 'passed']
        if values:
            result[mode] = dict(count=len(values), median=statistics.median(values),
                                minimum=min(values), maximum=max(values))
    if all(mode in result for mode in ('fresh', 'reuse')):
        result['medianReuseToFreshRatio'] = result['reuse']['median'] / result['fresh']['median']
    return result


def probe(source, entries, output, repetitions, host_note):
    source, output = source.resolve(), output.resolve()
    if repetitions < 3:
        raise ValueError('at least three measured repetitions are required')
    if source == output or source.is_relative_to(output) or output.is_relative_to(source):
        raise ValueError('source and evidence output must be disjoint')
    if ROOT == output or ROOT.is_relative_to(output) or output.is_relative_to(ROOT):
        raise ValueError('controller and evidence output must be disjoint')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schemaVersion=1, purpose='calibration', complete=False,
                  performanceQualified=False, samples=[], warmup=[], repetitions=repetitions,
                  hostNote=host_note, startedUtc=datetime.now(timezone.utc).isoformat(),
                  platform=platform.platform(), machine=platform.machine(),
                  python=sys.version, sdkRoot=str(SDK), entries=entries,
                  source=str(source), controller=str(ROOT))

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def measure(mode, repetition, warmup=False):
        target = output / ('warmup' if warmup else 'sample') / f'{repetition}-{mode}'
        target.parent.mkdir(parents=True, exist_ok=True)
        sample = dict(mode=mode, repetition=repetition, status='running', workspace=str(target))
        report['warmup' if warmup else 'samples'].append(sample)
        save()
        started = time.perf_counter()
        try:
            context = (fresh_view(source, target, entries) if mode == 'fresh' else
                       prepared_view(source, output / 'cache', target, entries))
            with context as result:
                sample['readySeconds'] = time.perf_counter() - started
                sample['work'] = result
                expected = mode == 'reuse'
                if result['reused'] != expected or result['discoveryExecuted'] == expected:
                    raise AssertionError(f'unexpected work for {mode}: {result}')
                if expected and (result['materializationExecuted'] or result['toolBuildsExecuted']):
                    raise AssertionError('reuse did not avoid materialization/tool builds')
            # Include lease teardown and its final input checks in the metric.
            sample['seconds'] = time.perf_counter() - started
            sample['status'] = 'passed'
        except BaseException as error:
            sample.update(status='failed', seconds=time.perf_counter() - started,
                          error=dict(type=type(error).__name__, message=str(error)))
            raise
        finally:
            save()

    try:
        report['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['sourceIdentityBefore'] = tree_snapshot(source)['sha256']
        report['toolsBefore'] = tool_identity()
        report['sdkInfo'] = subprocess.check_output([str(SDK / 'dotnet'), '--info'], text=True)
        # Warm fresh preparation first so any tool builds precede cache seeding.
        measure('fresh', 0, warmup=True)
        # Fresh MSBuild discovery can create assets caches under obj. Bind the
        # warmed source before either measured path, and report that setup
        # mutation explicitly rather than treating it as a timed source edit.
        report['sourceIdentityAfterWarmup'] = tree_snapshot(source)['sha256']
        report['toolsAfterWarmup'] = tool_identity()
        started = time.perf_counter()
        with prepared_view(source, output / 'cache', output / 'seed', entries) as seed:
            if seed['reused'] or not seed['discoveryExecuted']:
                raise AssertionError('seed must execute discovery')
            report['seed'] = dict(work=seed)
        report['seed']['seconds'] = time.perf_counter() - started
        measure('reuse', 0, warmup=True)
        for repetition in range(1, repetitions + 1):
            order = ('fresh', 'reuse') if repetition % 2 else ('reuse', 'fresh')
            for mode in order:
                measure(mode, repetition)
        report['sourceIdentityAfter'] = tree_snapshot(source)['sha256']
        if report['sourceIdentityAfter'] != report['sourceIdentityAfterWarmup']:
            raise AssertionError('calibration changed source inputs')
        report['toolsAfter'] = tool_identity()
        if report['toolsAfter'] != report['toolsAfterWarmup']:
            raise AssertionError('calibration changed tools during measured runs')
        report['summary'] = summarize(report['samples'])
        report['complete'] = True
    finally:
        save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'entries', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--host-note', required=True)
    args = parser.parse_args()
    probe(args.source, json.loads(args.entries.read_text()), args.output,
          args.repetitions, args.host_note)
