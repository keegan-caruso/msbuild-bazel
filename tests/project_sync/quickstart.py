"""Qualify the copied quickstart using plain Bazelisk, never a setup script.

Copy examples/quickstart beside the rules checkout as documented first. Seed and
recover run in independent source-only workspaces/containers; stop the producer
before recovery. This driver adds assertions and evidence to the documented commands.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('base', type=Path)
p.add_argument('report', type=Path)
p.add_argument('--bazel', default='bazel')
p.add_argument('--cache', required=True)
p.add_argument('--expect', type=Path)
a = p.parse_args()
w, base, report = [v.resolve() for v in [a.workspace, a.base, a.report]]
assert not base.exists(), 'Use a fresh output base'
report.parent.mkdir(parents=True, exist_ok=True)
start = [a.bazel, '--output_base=' + str(base), '--host_jvm_args=-Xmx1024m', '--ignore_all_rc_files']
flags = ['--jobs=2', '--disk_cache=', '--remote_cache=' + a.cache, '--remote_upload_local_results=' + str(not a.expect).lower(), '--remote_download_outputs=all']
rows = []

def run(name, command, tail=(), fail=False):
    execution = report.with_suffix('.' + name + '.execution.json')
    bep = report.with_suffix('.' + name + '.bep')
    result = subprocess.run(start + command + flags + ['--execution_log_json_file=' + str(execution), '--build_event_json_file=' + str(bep), *tail], cwd=w, capture_output=True, text=True)
    output = result.stdout + result.stderr
    report.with_suffix('.' + name + '.log').write_text(output)
    assert result.returncode == (3 if fail else 0), (name, output[-5000:])
    actions = []; text = execution.read_text(); decoder = json.JSONDecoder(); offset = 0
    while offset < len(text):
        if text[offset].isspace(): offset += 1; continue
        action, offset = decoder.raw_decode(text, offset)
        actions.append({key: action.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit', 'runner']})
    row = dict(case=name, exitCode=result.returncode, actions=actions)
    rows.append(row); print(row, flush=True)
    return actions, [json.loads(line) for line in bep.read_text().splitlines()], output

def executed(actions, mnemonic):
    return sorted({r['targetLabel'].split(':')[1] for r in actions if r['mnemonic'] == mnemonic and not r['cacheHit']})

generated = (w / 'projects.generated.bzl').read_bytes()
source = w / 'Library/Message.cs'; original = source.read_bytes()
try:
    sync, _, _ = run('sync', ['run', '//:sync'], ['--', '--check'])
    assert (w / 'projects.generated.bzl').read_bytes() == generated
    app, _, output = run('app', ['run', '//:App_App'])
    assert 'Hello from MSBuild and Bazel' in output
    tests, events, _ = run('test', ['test', '//:Tests_Tests'])
    hashes = {}
    outputs = w / 'bazel-out'
    for path in sorted(outputs.rglob('*')):
        if path.is_file() and any(part.endswith(('.reference', '.runtime')) for part in path.relative_to(outputs).parts):
            hashes[str(path.relative_to(outputs))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert hashes
    if a.expect:
        assert hashes == json.loads(a.expect.read_text())['hashes']
        assert all(r['cacheHit'] for r in sync + app + tests), 'Consumer executed an uncached action'
        results = [e['testResult'] for e in events if 'testResult' in e]
        assert len(results) == 1 and results[0].get('executionInfo', {}).get('cachedRemotely'), results
        forced, _, _ = run('forced-test', ['test', '//:Tests_Tests'], ['--nocache_test_results'])
        assert executed(forced, 'TestRunner') == ['Tests_Tests_net10_0']
        assert all(r['cacheHit'] for r in forced if r['mnemonic'] != 'TestRunner')
    else:
        noop, _, _ = run('noop', ['test', '//:Tests_Tests'])
        assert not executed(noop, 'MSBuildAssembly') and not executed(noop, 'TestRunner')
        source.write_bytes(original.replace(b'Hello from MSBuild and Bazel', b'Changed library body ' + base.name.encode()))
        actions, _, _ = run('body-failure', ['test', '//:Tests_Tests'], fail=True)
        assert executed(actions, 'MSBuildAssembly') == ['Library_Library_net10_0']
        assert executed(actions, 'TestRunner') == ['Tests_Tests_net10_0']
        source.write_bytes(original)
        repaired, _, _ = run('repair', ['test', '//:Tests_Tests'])
        assert not executed(repaired, 'MSBuildAssembly') and not executed(repaired, 'TestRunner')
    assert (w / 'projects.generated.bzl').read_bytes() == generated
    report.write_text(json.dumps(dict(mode='recover' if a.expect else 'seed', ambientDotnetOnPath=shutil.which('dotnet') is not None, generatedUnchanged=True, generatedSha256=hashlib.sha256(generated).hexdigest(), records=rows, hashes=hashes), indent=2) + '\n')
finally:
    source.write_bytes(original)
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
