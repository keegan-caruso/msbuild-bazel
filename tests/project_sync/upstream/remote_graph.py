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
parser.add_argument('--family', choices=['http', 'immutable', 'orchard', 'avalonia'], required=True)
parser.add_argument('--cache', required=True)
parser.add_argument('--seed', action='store_true')
parser.add_argument('--download-mode', choices=['all', 'toplevel'], default='all')
parser.add_argument('--expect', type=Path)
a = parser.parse_args()
if a.download_mode != 'all' and a.family != 'orchard':
    parser.error('Top-level download comparison currently requires the Orchard application graph')
w, base, raw, report = [p.resolve() for p in [a.workspace, a.base, a.raw, a.report]]
report.parent.mkdir(parents=True, exist_ok=True)
if not a.seed:
    assert a.expect and not base.exists(), 'Consumer requires a seed report and an empty output base'
target = '//:' + dict(http='src_Http_Http.Abstractions_test_Microsoft.AspNetCore.Http.Abstractions.Tests_net10_0', immutable='src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10_0', orchard='src_OrchardCore.Cms.Web_OrchardCore.Cms.Web').get(a.family, '')
targets = json.loads(raw.read_text())['targets'] if a.family == 'avalonia' else [target]
start = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m', '--output_base=' + str(base), '--ignore_all_rc_files']
flags = ['--jobs=2', '--disk_cache=', '--remote_cache=' + a.cache, '--remote_upload_local_results=' + str(a.seed).lower(), '--remote_download_outputs=' + a.download_mode]
records = []

def network_bytes():
    root = Path('/sys/class/net')
    if not root.exists(): return None
    return {key: sum(int((p / 'statistics' / (key + '_bytes')).read_text()) for p in root.iterdir() if p.name != 'lo') for key in ['rx', 'tx']}

def run(name, command, extra=()):
    execution = report.with_suffix('.' + name + '.execution.json')
    bep = report.with_suffix('.' + name + '.bep')
    before = network_bytes()
    began = time.monotonic()
    with report.with_suffix('.' + name + '.log').open('w') as log:
        result = subprocess.run(start + command + flags + ['--execution_log_json_file=' + str(execution), '--build_event_json_file=' + str(bep), *extra], cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    elapsed = round(time.monotonic() - began, 3)
    after = network_bytes()
    records.append(dict(case=name, seconds=elapsed, exitCode=result.returncode, guestNetworkBytes={k: after[k] - before[k] for k in before} if before else None))
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
    if a.family == 'orchard':
        smoke = Path(__file__).resolve().parents[2] / 'explicit_msbuild/orchard_compatibility/smoke.py'
        name = report.stem + '-smoke'
        subprocess.run([sys.executable, smoke, w, report.parent, name, '--target', target.split(':')[1]], check=True)
        actual = json.loads((report.parent / (name + '.json')).read_text())
        expected = json.loads(raw.read_text())
        assert [(r['path'], r['status'], r['contentType']) for r in actual] == [(r['path'], r['status'], r['contentType']) for r in expected]
        assert actual[1:] == expected[1:], 'Embedded assets differ from raw MSBuild'
        return len(actual)
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    def results(path):
        return Counter((r.get('testName'), r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
    if a.family == 'avalonia':
        baseline = json.loads(raw.read_text())
        for suite, label in baseline['testTargets'].items():
            actual = results(w / 'bazel-testlogs' / label.split(':')[1] / 'test.outputs/results.trx')
            assert actual == Counter({(name, outcome): count for name, outcome, count in baseline['outcomes'][suite]}), suite
        return sum(row[2] for rows in baseline['outcomes'].values() for row in rows)
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
    actions, events = run('recover', ['build' if a.family == 'orchard' else 'test', *targets])
    selected = [r for r in actions if r.get('mnemonic') != 'TestRunner']
    assert any(r.get('mnemonic') == 'MSBuildAssembly' for r in selected)
    if not a.seed:
        assert all(r.get('cacheHit') for r in selected), [(r.get('mnemonic'), r.get('targetLabel'), r.get('runner')) for r in selected if not r.get('cacheHit')]
        if a.family != 'orchard':
            tests = [e['testResult'] for e in events if 'testResult' in e]
            assert len(tests) == (5 if a.family == 'avalonia' else 1) and all(t.get('executionInfo', {}).get('cachedRemotely') for t in tests), tests
    hashes = {}
    outputs = w / 'bazel-out'
    for path in sorted(outputs.rglob('*')):
        if not path.is_file() or path.name.endswith('.params'):
            continue
        relative = path.relative_to(outputs)
        if any(part.endswith(('.reference', '.runtime', '.layout', '.generated')) for part in relative.parts):
            hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert hashes
    # Compare the complete application's declared runfiles even when Bazel is
    # allowed to leave intermediate outputs in CAS. Skip only the local manifest
    # containing physical checkout paths; file contents must remain exact.
    runtime_hashes = {}
    if a.family == 'orchard':
        runfiles = w / 'bazel-bin' / (target.split(':')[1] + '.runfiles')
        for directory, _, files in os.walk(runfiles, followlinks=True):
            for name in files:
                path = Path(directory) / name
                if path == runfiles / 'MANIFEST': continue
                runtime_hashes[path.relative_to(runfiles).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        assert runtime_hashes
    if a.expect:
        expected = json.loads(a.expect.read_text())
        if a.download_mode == 'all':
            assert hashes == expected['hashes'], 'Recovered output hashes differ'
        else:
            assert a.family == 'orchard' and expected.get('runfilesHashes'), 'Top-level comparison requires a complete application runfiles seed'
            assert all(expected['hashes'].get(path) == digest for path, digest in hashes.items()), 'Materialized output differs'
        if expected.get('runfilesHashes'):
            assert runtime_hashes == expected['runfilesHashes'], 'Recovered application runfiles differ'
    cached_count = verify()
    if not a.seed and a.family != 'orchard':
        forced, _ = run('execute', ['test', *targets], ['--nocache_test_results'])
        assert not any(r.get('mnemonic') != 'TestRunner' and not r.get('cacheHit') for r in forced), [(r.get('mnemonic'), r.get('targetLabel')) for r in forced if not r.get('cacheHit')]
        assert any(r.get('mnemonic') == 'TestRunner' and not r.get('cacheHit') for r in forced)
        assert verify() == cached_count
    generated = (w / 'projects.generated.bzl').read_bytes()
    sync_actions, _ = run('sync', ['run', '//:sync'], ['--', '--check'])
    assert generated == (w / 'projects.generated.bzl').read_bytes()
    if not a.seed:
        assert all(r.get('cacheHit') for r in sync_actions), 'Relocated sync rebuilt a declared tool'
    action_rows = [{key: r.get(key) for key in ['mnemonic', 'targetLabel', 'listedOutputs', 'cacheHit', 'runner', 'remoteCacheable']} for r in actions]
    report.write_text(json.dumps(dict(family=a.family, seed=a.seed, downloadMode=a.download_mode, runfilesHashes=runtime_hashes, records=records, actions=action_rows, syncActions=[{key:r.get(key) for key in ['mnemonic','targetLabel','cacheHit','runner']} for r in sync_actions], tests=cached_count if a.family != 'orchard' else None, smokeEndpoints=cached_count if a.family == 'orchard' else None, cachedTests=not a.seed and a.family != 'orchard', forcedExecution=not a.seed and a.family != 'orchard', hashes=hashes), indent=2) + '\n')
finally:
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
