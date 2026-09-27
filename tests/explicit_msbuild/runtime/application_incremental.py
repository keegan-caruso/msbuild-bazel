"""Prove app/runtime compilation boundaries with observable implementation edits."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--base', required=True)
a = p.parse_args()
w = a.workspace.resolve()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
start = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m',
         '--output_base='+a.base, '--ignore_all_rc_files']
flags = ['--jobs=2', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1',
         '--disk_cache=', '--remote_cache=']
manifest = json.loads((w/'subset.json').read_text())
console_label = manifest['managed']['System.Console.dll']
package, target = console_label.removeprefix('//').split(':')
# Runtime consumers can explicitly request implementation references. Check
# the authored contract producer, rather than mistaking those bytes for a ref.
pairs = []
for line in (w/package/'BUILD.bazel').read_text().splitlines():
    if line.startswith('msbuild_assembly('):
        attributes = {kw.arg: ast.literal_eval(kw.value) for kw in ast.parse(line).body[0].value.keywords}
        if attributes['implementation'] == ':'+target and not attributes.get('use_implementation_reference'):
            pairs.append(attributes['contract'].removeprefix(':'))
assert len(pairs) == 1, pairs
console_reference = w/'bazel-bin'/package/(pairs[0]+'.reference/System.Console.dll')
app = w/'app/Program.cs'
console = w/'upstream/src/libraries/System.Console/src/System/Console.cs'
original_app, original_console = app.read_text(), console.read_text()
records = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(case, greeting):
    execution = out/(case+'.execution.json')
    before = time.monotonic()
    with (out/(case+'.log')).open('w') as log:
        result = subprocess.run(start+['build', '//app:app', '--execution_log_json_file='+str(execution), *flags],
                                cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    assert result.returncode == 0, out/(case+'.log')
    data = execution.read_text()
    decoder = json.JSONDecoder()
    actions = []
    offset = 0
    while offset < len(data):
        if data[offset].isspace():
            offset += 1
            continue
        row, offset = decoder.raw_decode(data, offset)
        if not row.get('cacheHit'):
            actions.append({key: row.get(key) for key in ['mnemonic', 'targetLabel']})
    result = subprocess.run([w/'bazel-bin/app/app'], cwd=w, capture_output=True, text=True, timeout=60)
    (out/(case+'.app.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == 0 and result.stdout.splitlines()[0] == greeting, result
    host = w/'bazel-bin/runtime/tree.layout'
    row = dict(case=case, seconds=round(time.monotonic()-before, 3), executed=actions,
               appHash=sha(w/'bazel-bin/app/app.runtime/App.dll'), consoleReferenceHash=sha(console_reference),
               hostHashes={str(path.relative_to(host)): sha(path) for path in host.rglob('*')
                           if path.is_file() and (path.suffix in ['.dll', '.so'] or path.name == 'dotnet')},
               greeting=result.stdout.splitlines()[0])
    records.append(row)
    (out/'report.json').write_text(json.dumps(records, indent=2)+'\n')
    print(case, len(actions), 'executed actions', flush=True)
    return row


hello = 'Hello from source-built .NET'
needle = 'public static void WriteLine(string? value)\n        {\n            Out.WriteLine(value);'
assert original_console.count(needle) == 1
try:
    baseline = build('baseline', hello)
    noop = build('noop', hello)
    assert not noop['executed'], noop['executed']
    console.write_text(original_console.replace(needle, needle.replace('Out.WriteLine(value);',
                       'Out.WriteLine(value == "'+hello+'" ? value + " [runtime edit]" : value);')))
    runtime = build('runtime-body', hello+' [runtime edit]')
    compiled = {row['targetLabel'] for row in runtime['executed'] if row['mnemonic'] == 'MSBuildAssembly'}
    assert console_label in compiled and '//app:app' not in compiled, compiled
    assert not any(row['mnemonic'] == 'RuntimeNative' for row in runtime['executed'])
    assert runtime['appHash'] == baseline['appHash']
    assert runtime['consoleReferenceHash'] == baseline['consoleReferenceHash']
    assert runtime['hostHashes'] != baseline['hostHashes']
    console.write_text(original_console)
    restored = build('runtime-revert', hello)
    assert restored['hostHashes'] == baseline['hostHashes']
    assert original_app.count(hello) == 1
    app.write_text(original_app.replace(hello, 'Hello from app edit'))
    edited = build('app-body', 'Hello from app edit')
    compiled = [row['targetLabel'] for row in edited['executed'] if row['mnemonic'] == 'MSBuildAssembly']
    assert compiled == ['//app:app'], compiled
    assert not any(row['mnemonic'] == 'RuntimeNative' for row in edited['executed'])
    assert edited['hostHashes'] == baseline['hostHashes']
    assert edited['appHash'] != baseline['appHash']
finally:
    app.write_text(original_app)
    console.write_text(original_console)
restored = build('app-revert', hello)
assert restored['hostHashes'] == baseline['hostHashes'] and restored['appHash'] == baseline['appHash']
print('Runtime edits preserve app compilation; app edits preserve runtime products')
