"""Seed or recover the app and source runtime in an empty Bazel output base."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--base', type=Path, required=True)
p.add_argument('--cache', required=True)
p.add_argument('--seed', action='store_true')
p.add_argument('--expect', type=Path)
a = p.parse_args()
w, out, base = a.workspace.resolve(), a.output.resolve(), a.base.resolve()
assert not base.exists(), 'Use an empty output base'
assert a.seed or a.expect, 'Recovery needs the producer report'
out.mkdir(parents=True, exist_ok=False)
start = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m',
         '--output_base='+str(base), '--ignore_all_rc_files']
flags = ['--jobs=2', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1',
         '--disk_cache=', '--remote_cache='+a.cache, '--remote_download_outputs=all',
         '--remote_upload_local_results='+str(a.seed).lower()]
execution = out/'execution.json'
before = time.monotonic()
with (out/'build.log').open('w') as log:
    result = subprocess.run(start+['build', '//app:app', *flags, '--execution_log_json_file='+str(execution)],
                            cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
assert result.returncode == 0, out/'build.log'
seconds = round(time.monotonic()-before, 3)
data = execution.read_text()
decoder = json.JSONDecoder()
actions = []
offset = 0
while offset < len(data):
    if data[offset].isspace():
        offset += 1
        continue
    row, offset = decoder.raw_decode(data, offset)
    actions.append({key: row.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit']})
counts = {}
for mnemonic in ['MSBuildAssembly', 'RuntimeNative', 'MSBuildLayout']:
    selected = [row for row in actions if row['mnemonic'] == mnemonic]
    assert selected, mnemonic
    if not a.seed:
        assert all(row['cacheHit'] for row in selected), [row for row in selected if not row['cacheHit']]
    counts[mnemonic] = dict(total=len(selected), cacheHits=sum(bool(row['cacheHit']) for row in selected))
assert counts['RuntimeNative']['total'] == 5
assert counts['MSBuildAssembly']['total'] >= 121
hashes = {}
outputs = w/'bazel-out'
for path in sorted(outputs.rglob('*')):
    if not path.is_file() or path.name.endswith('.params'):
        continue
    relative = path.relative_to(outputs)
    if any(part.endswith(('.reference', '.runtime', '.layout', '.generated')) for part in relative.parts):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                digest.update(block)
        hashes[str(relative)] = digest.hexdigest()
assert hashes
if a.expect:
    expected = json.loads(a.expect.read_text())
    assert hashes == expected['hashes'], 'Recovered products differ from the producer'
    assert {key: value['total'] for key, value in counts.items()} == {key: value['total'] for key, value in expected['actions'].items()}
subprocess.run([sys.executable, Path(__file__).with_name('application_verify.py'), w, out/'application.json'], check=True)
(out/'report.json').write_text(json.dumps(dict(seed=a.seed, seconds=seconds, actions=counts,
                                             hashes=hashes, appExecutionVerified=True), indent=2)+'\n')
print('Verified', 'producer' if a.seed else 'cache consumer', counts, len(hashes), 'output hashes', flush=True)
