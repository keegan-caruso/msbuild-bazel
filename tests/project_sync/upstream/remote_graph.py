"""Seed or recover a complete generated graph through an independent HTTP cache.

Copy only workspace inputs and this rules checkout to a separate container. Stop
its producer before consuming; use a different workspace path and an absent base.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
for name in ['workspace', 'base', 'raw', 'report']:
    parser.add_argument(name, type=Path)
parser.add_argument('--family', choices=['http', 'immutable'], required=True)
parser.add_argument('--cache', required=True)
parser.add_argument('--seed', action='store_true')
parser.add_argument('--expect', type=Path)
a = parser.parse_args()
w, base, raw, report = [p.resolve() for p in [a.workspace, a.base, a.raw, a.report]]
report.parent.mkdir(parents=True, exist_ok=True)
if not a.seed:
    assert a.expect and not base.exists(), 'Consumer requires a seed report and an empty output base'
target = '//:' + ('src_Http_Http.Abstractions_test_Microsoft.AspNetCore.Http.Abstractions.Tests_net10_0' if a.family == 'http' else 'src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10_0')
start = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m', '--output_base=' + str(base), '--ignore_all_rc_files']
flags = ['--jobs=2', '--disk_cache=', '--remote_cache=' + a.cache, '--remote_upload_local_results=' + str(a.seed).lower(), '--remote_download_outputs=all']
records = []

def run(name, command, extra=()):
    execution = report.with_suffix('.' + name + '.execution.json')
    bep = report.with_suffix('.' + name + '.bep')
    began = time.monotonic()
    with report.with_suffix('.' + name + '.log').open('w') as log:
        result = subprocess.run(start + command + flags + ['--execution_log_json_file=' + str(execution), '--build_event_json_file=' + str(bep), *extra], cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    records.append(dict(case=name, seconds=round(time.monotonic() - began, 3), exitCode=result.returncode))
    print(name, records[-1], flush=True)
    assert result.returncode == 0, report.with_suffix('.' + name + '.log')
    text = execution.read_text(); decoder = json.JSONDecoder(); offset = 0; actions = []
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        row, offset = decoder.raw_decode(text, offset)
        actions.append(row)
    return actions, [json.loads(line) for line in bep.read_text().splitlines()]

def verify():
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    def results(path):
        return Counter((r.get('testName'), r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
    actual = results(w / 'bazel-testlogs' / target.split(':')[1] / 'test.outputs/results.trx')
    expected = results(raw)
    if a.family == 'immutable':
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'explicit_msbuild/runtime'))
        from case_names import normalized
        assert normalized(actual) == normalized(expected)
        built = w / 'bazel-bin/src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10_0.runtime/System.Collections.Immutable.dll'
        digest = hashlib.sha256(built.read_bytes()).hexdigest().upper()
        probes = list((w / 'bazel-testlogs' / target.split(':')[1] / 'test.outputs').glob('loaded-source-*.json'))
        assert probes and all(json.loads(p.read_text())['sha256'] == digest for p in probes)
    else:
        assert actual == expected
    return sum(actual.values())

try:
    if a.seed and base.exists():
        subprocess.run(start + ['clean'], cwd=w, check=True, stdout=subprocess.DEVNULL)
    actions, events = run('recover', ['test', target])
    selected = [r for r in actions if r.get('mnemonic') != 'TestRunner']
    assert any(r.get('mnemonic') == 'MSBuildAssembly' for r in selected)
    if not a.seed:
        assert all(r.get('cacheHit') for r in selected), [(r.get('mnemonic'), r.get('targetLabel'), r.get('runner')) for r in selected if not r.get('cacheHit')]
        tests = [e['testResult'] for e in events if 'testResult' in e]
        assert len(tests) == 1 and tests[0].get('executionInfo', {}).get('cachedRemotely'), tests
    hashes = {}
    outputs = w / 'bazel-out'
    for path in sorted(outputs.rglob('*')):
        if not path.is_file() or path.name.endswith('.params'):
            continue
        relative = path.relative_to(outputs)
        if any(part.endswith(('.reference', '.runtime', '.layout', '.generated')) for part in relative.parts):
            hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert hashes
    if a.expect:
        assert hashes == json.loads(a.expect.read_text())['hashes'], 'Recovered output hashes differ'
    cached_count = verify()
    if not a.seed:
        forced, _ = run('execute', ['test', target], ['--nocache_test_results'])
        assert not any(r.get('mnemonic') != 'TestRunner' and not r.get('cacheHit') for r in forced), [(r.get('mnemonic'), r.get('targetLabel')) for r in forced if not r.get('cacheHit')]
        assert any(r.get('mnemonic') == 'TestRunner' and not r.get('cacheHit') for r in forced)
        assert verify() == cached_count
    generated = (w / 'projects.generated.bzl').read_bytes()
    sync_actions, _ = run('sync', ['run', '//:sync'], ['--', '--check'])
    assert generated == (w / 'projects.generated.bzl').read_bytes()
    if not a.seed:
        assert all(r.get('cacheHit') for r in sync_actions), 'Relocated sync rebuilt a declared tool'
    action_rows = [{key: r.get(key) for key in ['mnemonic', 'targetLabel', 'listedOutputs', 'cacheHit', 'runner', 'remoteCacheable']} for r in actions]
    report.write_text(json.dumps(dict(family=a.family, seed=a.seed, records=records, actions=action_rows, syncActions=[{key:r.get(key) for key in ['mnemonic','targetLabel','cacheHit','runner']} for r in sync_actions], tests=cached_count, cachedTests=not a.seed, forcedExecution=not a.seed, hashes=hashes), indent=2) + '\n')
finally:
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
