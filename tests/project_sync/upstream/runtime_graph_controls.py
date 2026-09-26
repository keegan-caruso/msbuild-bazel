"""Full Immutable graph synchronization, API and rejection controls."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

workspace, base, out = (Path(p).resolve() for p in sys.argv[1:])
out.mkdir(parents=True, exist_ok=False)
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(base), '--ignore_all_rc_files']
target = '//:src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10_0'
rows = []
def run(name, args, success=True):
    result = subprocess.run(cmd + args, cwd=workspace, text=True, capture_output=True)
    log = result.stdout + result.stderr
    (out / (name + '.log')).write_text(log)
    assert (result.returncode == 0) == success, (name, log[-4000:])
    rows.append(dict(case=name, exitCode=result.returncode))
    print(name, result.returncode, flush=True)
    return log

generated = workspace / 'projects.generated.bzl'
original_generated = generated.read_bytes()
run('repeat-sync', ['run', '//:sync', '--jobs=2'])
assert generated.read_bytes() == original_generated
run('check', ['run', '//:sync', '--', '--check'])
assert generated.read_text().count('    project = ') == 36
assert not any(line.startswith(('msbuild_library(', 'msbuild_binary(')) for line in (workspace / 'BUILD.bazel').read_text().splitlines())
rows.append(dict(case='generated-producers', count=36))
source = workspace / 'src/libraries/System.Collections.Immutable/src/System/Collections/Immutable/ImmutableArray_1.cs'
contract = workspace / 'src/libraries/System.Collections.Immutable/ref/System.Collections.Immutable.cs'
original = source.read_text()
original_contract = contract.read_text()
reference = workspace / 'bazel-bin/src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net10_0.reference/System.Collections.Immutable.dll'
digest = lambda: hashlib.sha256(reference.read_bytes()).hexdigest()
baseline = digest()
try:
    pattern = r'(public readonly partial struct ImmutableArray<T>[^\n]*\n\s*\{)'
    replacement = r'\1\n        /// <summary>Qualification API probe.</summary>\n        public bool QualificationProbe => IsEmpty;'
    updated, count = re.subn(pattern, replacement, original, count=1)
    assert count == 1
    updated_contract, count = re.subn(pattern, r'\1\n        public bool QualificationProbe { get { throw null; } }', original_contract, count=1)
    assert count == 1
    source.write_text(updated)
    contract.write_text(updated_contract)
    run('api-edit', ['test', target, '--jobs=2', '--build_event_json_file=' + str(out / 'api.bep')])
    events = [json.loads(line) for line in (out / 'api.bep').read_text().splitlines()]
    tests = [e['testResult'] for e in events if 'testResult' in e]
    assert len(tests) == 1 and not tests[0].get('cachedLocally', False)
    assert digest() != baseline
    built = workspace / 'bazel-bin/src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10_0.runtime/System.Collections.Immutable.dll'
    proofs = list((workspace / 'bazel-testlogs' / target.split(':')[1] / 'test.outputs').glob('loaded-source-*.json'))
    expected = hashlib.sha256(built.read_bytes()).hexdigest().upper()
    assert proofs and all(json.loads(p.read_text())['sha256'] == expected for p in proofs)
    rows.append(dict(case='api-invalidation', referenceChanged=True, testsExecuted=True, loadedAssemblySha256=expected))
finally:
    source.write_text(original)
    contract.write_text(original_contract)
    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
run('api-restored', ['test', target, '--jobs=2'])
assert digest() == baseline
try:
    source.unlink()
    diagnostic = run('missing-source', ['run', '//:sync', '--', '--check'], success=False)
    assert 'stale' in diagnostic or 'Missing' in diagnostic
    assert generated.read_bytes() == original_generated
finally:
    source.write_text(original)
run('source-repaired', ['run', '//:sync', '--', '--check'])
# The source-built task input must be needed even on a warm tool cache.
tool = workspace / 'src/tools/illink/src/ILLink.Tasks/LinkTask.cs'
original_tool = tool.read_bytes()
try:
    tool.unlink()
    diagnostic = run('missing-tool-source', ['run', '//:sync', '--', '--check'], success=False)
    assert 'LinkTask.cs' in diagnostic
    assert generated.read_bytes() == original_generated
finally:
    tool.write_bytes(original_tool)
run('tool-repaired', ['run', '//:sync', '--', '--check'])
mapping = workspace / 'sync.json'
original_mapping = mapping.read_bytes()
try:
    data = json.loads(original_mapping)
    project = data['projects']['src/libraries/System.Collections.Immutable/tests/System.Collections.Immutable.Tests.csproj']
    assert project.pop('assemblySelections')
    mapping.write_text(json.dumps(data, indent=2) + '\n')
    run('ambiguous-sync', ['run', '//:sync', '--jobs=2'])
    diagnostic = run('ambiguous-assemblies', ['test', target, '--jobs=2'], success=False)
    assert any(v in diagnostic.lower() for v in ['ambiguous', 'duplicate', 'conflict', 'multiple']), diagnostic[-4000:]
finally:
    mapping.write_bytes(original_mapping)
    generated.write_bytes(original_generated)
    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
run('repaired', ['run', '//:sync', '--', '--check'])
run('repaired-tests', ['test', target, '--jobs=2'])
(out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
