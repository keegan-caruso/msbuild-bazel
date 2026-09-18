"""Break down retained Bazel traces and runner phases without summing nested spans."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics
from profile import summarize


def report(path):
    source = json.loads(path.read_text())
    if not source['accepted']:
        raise ValueError('Incomplete measurement')
    samples = []
    decoder = json.JSONDecoder()
    for sample in source['samples']:
        root = path.parent / sample['kind'] / (sample['case'] + '-' + str(sample['repetition'])) / 'n'
        state = root / 'state/b'
        profiles = list(state.glob('command-*.profile.gz'))
        if len(profiles) != 1:
            raise ValueError('Expected one build profile')
        trace = json.loads(gzip.decompress(profiles[0].read_bytes()))['traceEvents']
        complete = [e for e in trace if e.get('ph') == 'X']
        def seconds(name):
            return sum(e['dur'] for e in complete if e.get('name') == name) / 1e6
        marks = {e['name']: e['ts'] for e in trace if e.get('cat') == 'build phase marker' and e.get('ph') == 'i'}
        build = next(e for e in complete if e.get('name') == 'MsbuildNativeCache build.bundle')
        sdk_packages = [e for e in complete if e.get('cat') == 'package creation' and 'dotnet//' in e['name']]
        execution = (root / 'result/execution.json').read_text()
        sdk_inputs = []
        while execution.strip():
            action, end = decoder.raw_decode(execution.lstrip())
            execution = execution.lstrip()[end:]
            inputs = [i for i in action['inputs'] if '+_repo_rules+dotnet/' in i['path']]
            names = [i['path'] for i in inputs]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate declared SDK input')
            signature = sorted((i['path'].split('+dotnet/', 1)[1], i.get('digest')) for i in inputs)
            sdk_inputs.append(dict(mnemonic=action['mnemonic'], count=len(inputs),
                                   bytes=sum(int(i.get('digest', {}).get('sizeBytes', 0)) for i in inputs),
                                   sha256=hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()))
        if len({i['sha256'] for i in sdk_inputs}) != 1:
            raise ValueError('Build/test SDK inputs differ')
        configured = int(re.search(r'(\d+) targets configured', (root / 'result/bazel.log').read_text())[1])
        generated = root / 'state/g'
        timings = json.loads((generated / 'bazel-bin/build.diagnostics/timings.json').read_text())
        tests = list(state.glob('execroot/*/bazel-out/*/testlogs/test/test.outputs/report.json'))
        value = dict(kind=sample['kind'], case=sample['case'], repetition=sample['repetition'],
                     **summarize(profiles[0]), configuredTargets=configured,
                     sdkPackageLoads=len(sdk_packages), sdkInputs=sdk_inputs,
                     sdkPackageSeconds=sum(e['dur'] for e in sdk_packages)/1e6,
                     beforeFirstBuildActionSeconds=(build['ts']-marks['Load, analyze dependencies and build artifacts'])/1e6,
                     runfilesSeconds=seconds('Create symlink tree in-process'),
                     sandboxInputsSeconds=seconds('sandbox.createInputs'),
                     runner=timings, test=json.loads(tests[0].read_text())['phases'] if tests else {})
        samples.append(value)
    medians = []
    keys = ['configuredTargets', 'launchSeconds', 'moduleMappingSeconds', 'sdkPackageSeconds',
            'beforeFirstBuildActionSeconds', 'runfilesSeconds', 'sandboxCreateSeconds', 'sandboxInputsSeconds', 'criticalPathSeconds']
    for kind, case in sorted({(s['kind'], s['case']) for s in samples}):
        selected = [s for s in samples if (s['kind'], s['case']) == (kind, case)]
        result = dict(kind=kind, case=case, **{k: statistics.median(s[k] for s in selected) for k in keys})
        for category in ('runner', 'test'):
            result[category] = {key: statistics.median(s[category][key] for s in selected)
                                for key in selected[0][category]}
        medians.append(result)
    return dict(source=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                revision=source['revision'], accepted=True, samples=samples, medians=medians)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps([report(p) for p in args.reports], indent=2) + '\n')
