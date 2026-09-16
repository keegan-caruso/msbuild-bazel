"""Evaluate owned local reports against the MVP budget frozen before issue #7.

This is a measurement gate, not permission to reuse any mutable input or cache.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from probe_preparation_performance import SDK, summarize

FROZEN_BUDGET_SHA256 = 'c89f378450e1d7196ce30931e7c45990d7a5511c63bf431d39b6299cec0f84c1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def evaluate(budget_bytes, reports, end_to_end):
    require(hashlib.sha256(budget_bytes).hexdigest() == FROZEN_BUDGET_SHA256,
            'budget differs from the predeclared MVP budget')
    budget = json.loads(budget_bytes)
    require(set(reports) == set(budget['workloads']), 'missing or unexpected workload')
    result = dict(schemaVersion=1, performanceQualified=False, scope='local MVP preparation only',
                  budgetSha256=FROZEN_BUDGET_SHA256, workloads={}, failures=[])
    count = budget['measuredRepetitionsPerMode']
    for name, report in reports.items():
        require(report.get('complete') is True and report.get('purpose') == 'calibration', name + ': incomplete calibration')
        require(report['repetitions'] == count, name + ': wrong repetition count')
        project = 'App/App.csproj' if name == 'small' else budget['workloads'][name]['project']
        require(report['entries'] == [dict(project=project, globalProperties=dict(Configuration='Release', TargetFramework='net10.0'))], name + ': wrong request')
        require(report['sourceIdentityAfterWarmup'] == report['sourceIdentityAfter'], name + ': source changed')
        require(report['toolsAfterWarmup'] == report['toolsAfter'], name + ': tools changed')
        require(report['seed']['work']['reused'] is False and report['seed']['work']['discoveryExecuted'] is True, name + ': invalid seed')
        for samples, expected_count, repetitions in [(report['warmup'], 2, [0]), (report['samples'], count * 2, range(1, count + 1))]:
            expected = {(mode, n) for mode in ('fresh', 'reuse') for n in repetitions}
            require(len(samples) == expected_count and {(s['mode'], s['repetition']) for s in samples} == expected, name + ': missing or duplicate samples')
            for sample in samples:
                require(sample['status'] == 'passed', name + ': failed sample')
                seconds = sample['seconds']
                require(isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and math.isfinite(seconds) and seconds > 0, name + ': invalid duration')
                work = sample['work']
                if sample['mode'] == 'reuse':
                    require(all(work.get(key) is value for key, value in budget['requiredReuseWork'].items()), name + ': wrong reuse work')
                else:
                    require(work.get('reused') is False and all(work.get(key) is True for key in ('discoveryExecuted', 'materializationExecuted', 'toolBuildsExecuted')), name + ': wrong fresh work')
        # Recompute from individual successful samples, never trust a stored median.
        summary = summarize(report['samples'])
        limits = budget['workloads'][name]
        passed = (summary['medianReuseToFreshRatio'] <= limits['maxMedianReuseToFreshRatio'] and
                  summary['reuse']['median'] <= limits['maxMedianReuseSeconds'])
        result['workloads'][name] = dict(passed=passed, summary=summary)
        if not passed: result['failures'].append(name + ': exceeded preparation budget')
    small, serilog = reports['small'], reports['serilog']
    for field in ('revision', 'toolsAfter', 'sdkRoot', 'python', 'machine', 'platform'):
        require(small[field] == serilog[field], 'workloads have different ' + field)
    require(small['machine'] == 'arm64', 'unqualified architecture')
    require(small['sdkRoot'] == str(SDK), 'unqualified SDK installation')
    require(end_to_end.get('accepted') is True and end_to_end['adapterRevision'] == small['revision'], 'missing same-candidate Build/Test comparison')
    require(end_to_end['revision'] == budget['workloads']['serilog']['revision'], 'wrong Serilog revision')
    samples = end_to_end['samples']
    expected = {(case, system, n) for case in ('fresh', 'unchanged', 'sourceEdited', 'recovered') for system in ('ordinary', 'bazel') for n in range(1, count + 1)}
    require(len(samples) == len(expected) and {(s['case'], s['system'], s['repetition']) for s in samples} == expected, 'missing or duplicate Build/Test samples')
    require(all(s['status'] == 'passed' for s in samples), 'failed Build/Test sample')
    result.update(candidateRevision=small['revision'], performanceQualified=not result['failures'],
                  endToEndSummaries=end_to_end['summaries'],
                  limitation='Only preparation latency is budget-qualified. End-to-end adapter overhead and recovery comparison differences remain reported; no scale or cross-platform claim.')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('budget', 'small', 'serilog', 'end-to-end', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = dict(schemaVersion=1, performanceQualified=False)
    try:
        raw = {name: getattr(args, name).read_bytes() for name in ('small', 'serilog', 'end_to_end')}
        result = evaluate(args.budget.read_bytes(), {name: json.loads(raw[name]) for name in ('small', 'serilog')}, json.loads(raw['end_to_end']))
        result['reportSha256'] = {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}
    except (ValueError, KeyError, TypeError, OSError) as error:
        result['error'] = str(error)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    raise SystemExit(0 if result['performanceQualified'] else 1)
