"""Repeated real catalog-app edits, HTTP/tests and Publish with resource evidence.

This measures one application and explicitly selected worker retention. It does
not benchmark source-runtime production or compare raw MSBuild/Bazel speedups.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.measure import command
from benchmarks.resources import GuestMemory, allocated_bytes

ROOT = Path(__file__).resolve().parents[1]


def percentiles(values):
    if len(values) < 5 or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError('At least five finite, nonnegative successful observations are required')
    return dict(count=len(values), p50Seconds=statistics.median(values),
                p95Seconds=sorted(values)[math.ceil(.95*len(values))-1],
                maximumSeconds=max(values), method='nearest-rank p95; five samples make p95 the maximum')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new owned fixture/report directory outside the checkout')
    parser.add_argument('--revision', required=True, help='exact rules revision used for the qualification copy')
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--timeout', type=int, default=180, help='per-command deadline in seconds')
    args = parser.parse_args()
    if platform.system() != 'Linux' or platform.machine() != 'aarch64':
        parser.error('Requires the qualified Linux ARM64 guest')
    if args.samples < 5 or args.timeout < 1:
        parser.error('Use at least five samples and a positive timeout')
    base = args.directory.resolve()
    if base.is_relative_to(ROOT) or ROOT.is_relative_to(base):
        parser.error('Use a fresh directory outside the rules checkout')
    base.mkdir(parents=True, exist_ok=False)
    work, reports, output = base/'consumer', base/'reports', base/'bazel'
    reports.mkdir()
    shutil.copytree(ROOT/'examples/catalog-web', work)
    module = work/'MODULE.bazel'
    text = module.read_text()
    assert text.count('path = "../msbuild-bazel"') == 1
    module.write_text(text.replace('path = "../msbuild-bazel"', 'path = '+json.dumps(str(ROOT))))
    build = work/'BUILD.bazel'
    build.write_text(build.read_text().replace('app_graph(name = "build")',
        'app_graph(name = "build", linux_stable_paths=True, linux_worker=True)').replace(
        'name = "publish",', 'name = "publish", linux_stable_paths=True, linux_worker=True,'))
    mapping = work/'mappings.json'
    data = json.loads(mapping.read_text())
    data['projectDefaults']['preparedRestore'] = True
    mapping.write_text(json.dumps(data)+'\n')
    environment = dict(os.environ)
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN']:
        environment.pop(name, None)
    launcher = environment.get('RULES_MSBUILD_BAZEL', str(ROOT/'scripts/bazel-launcher.sh'))
    common = ['--jobs=2', '--local_test_jobs=1', '--worker_max_instances=MSBuildGraph=1',
              '--worker_sandboxing', '--remote_cache=', '--disk_cache=', '--noshow_progress']
    rows = []
    framework = ET.parse(work/'Directory.Build.props').findtext('.//TargetFramework')
    assert framework
    metadata = dict(revision=args.revision, workload='catalog-web: five projects, Razor/API, JSON data, packages/analyzer',
                    platform=platform.platform(), architecture=platform.machine(),
                    sdk=json.loads((work/'global.json').read_text())['sdk']['version'],
                    targetFramework=framework, cpus=os.cpu_count(), samplesPerCase=args.samples, timingScope='Bazel command including app smoke execution where applicable',
                    memoryScope='whole guest, sampled; RSS sums double-count shared pages',
                    diskScope='owned consumer/output-base allocated blocks at command boundaries; includes SDK/repository expansions under output base; excludes external image/preinstalled tools and other host state',
                    workerSelection='explicit Build and Publish workers',
                    sourceProduction=False)
    (reports/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')

    def invoke(label, verb, targets, extra=(), expected=None):
        before = allocated_bytes([work, output])
        start = time.monotonic()
        failure = None
        try:
            with GuestMemory() as memory:
                argv = [launcher, '--ignore_all_rc_files', '--output_base='+str(output), verb,
                        *targets, *common, *extra]
                # command() preserves failed/timed-out observations. Resource
                # samples are written even when that helper raises.
                result, seconds = command(argv, work, reports/(label+'.log'), timeout=args.timeout, environment=environment)
                result.check_returncode()
                if expected:
                    assert expected in (reports/(label+'.log')).read_text(), label
        except BaseException as error:
            failure = type(error).__name__+': '+str(error)
            raise
        finally:
            row = dict(label=label, wallSeconds=time.monotonic()-start, failure=failure,
                       allocatedBeforeBytes=before, allocatedAfterBytes=allocated_bytes([work, output]),
                       memory=memory.summary())
            (reports/(label+'.resources.json')).write_text(json.dumps(dict(summary=row, samples=memory.samples), indent=2)+'\n')
            rows.append(row)
            (reports/'rows.json').write_text(json.dumps(rows, indent=2)+'\n')
        return row

    try:
        invoke('bootstrap-sync', 'run', ['//:sync'])
        invoke('bootstrap-check', 'run', ['//:sync'], ['--', '--check'])
        invoke('seed', 'run', ['//:app'], ['--', '--smoke'], 'HTTP: warehouse-v1')
        reference = work/f'bazel-bin/build.graph/workspace/Data/obj/Release/{framework}/ref/Data.dll'
        seed_reference = hashlib.sha256(reference.read_bytes()).hexdigest()
        source = work/'Data/CatalogStore.cs'
        original = source.read_text()
        assert original.count('warehouse-v1') == 1
        for case in ['body', 'api']:
            for index in range(args.samples):
                value = f'warehouse-{case}-{index}'
                text = original.replace('warehouse-v1', value)
                if case == 'api':
                    text = text.replace('    public static string Revision()',
                        f'    public static int Added{index}() => {index};\n    public static string Revision()')
                source.write_text(text)
                row = invoke(f'{case}-{index}', 'run', ['//:app'], ['--', '--smoke'], 'HTTP: '+value)
                report = json.loads((work/'bazel-bin/build.graph/report.json').read_text())
                if case == 'body':
                    assert (report['hits'], report['misses']) == (4, 1), report
                else:
                    assert report['misses'] > 1 and report['hits'] >= 1, report
                row['graph'] = report
                row['referenceSha256'] = hashlib.sha256(reference.read_bytes()).hexdigest()
                assert (row['referenceSha256'] == seed_reference) == (case == 'body'), row
                invoke(f'{case}-{index}-tests', 'test', ['//:tests', '//:web_test'], ['--nocache_test_results', '--test_output=all'], 'UNIT: '+value)
                if case == 'body':
                    invoke(f'publish-{index}', 'run', ['//:published_app'], ['--', '--smoke'], 'HTTP: '+value)
                    invoke(f'publish-{index}-tests', 'test', ['//:published_test'], ['--nocache_test_results', '--test_output=errors'])
        distributions = {case: percentiles([row['wallSeconds'] for row in rows if row['label'].startswith(case+'-') and not row['label'].endswith('-tests')])
                         for case in ['body', 'api', 'publish']}
        (reports/'summary.json').write_text(json.dumps(dict(metadata=metadata, distributions=distributions, rows=rows,
            budgetDecision='No production budget change from one application; source-production sustained qualification remains separate'), indent=2)+'\n')
        print(json.dumps(distributions, indent=2))
    finally:
        subprocess.run([launcher, '--ignore_all_rc_files', '--output_base='+str(output), 'shutdown'], cwd=work,
                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=30)


if __name__ == '__main__':
    main()
