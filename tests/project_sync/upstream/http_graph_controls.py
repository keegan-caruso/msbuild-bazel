"""Full HTTP graph regeneration, API-edit and missing-input controls.

Run after controls.py has established raw outcome parity and body-edit behavior.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

workspace, base, out = (Path(p).resolve() for p in sys.argv[1:])
out.mkdir(parents=True, exist_ok=False)
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(base), '--ignore_all_rc_files']
target = '//:src_Http_Http.Abstractions_test_Microsoft.AspNetCore.Http.Abstractions.Tests_net10_0'
rows = []
def run(name, args, success=True):
    result = subprocess.run(cmd + args, cwd=workspace, text=True, capture_output=True)
    (out / (name + '.log')).write_text(result.stdout + result.stderr)
    assert (result.returncode == 0) == success, (name, (result.stdout + result.stderr)[-3000:])
    rows.append(dict(case=name, exitCode=result.returncode))
    print(name, result.returncode, flush=True)
    return result.stdout + result.stderr

generated = workspace / 'projects.generated.bzl'
original_generated = generated.read_bytes()
run('repeat-sync', ['run', '//:sync', '--jobs=2'])
assert generated.read_bytes() == original_generated
run('check', ['run', '//:sync', '--', '--check'])
assert generated.read_text().count('    project = ') == 44
assert not any(line.startswith(('msbuild_library(', 'msbuild_binary(')) for line in (workspace / 'BUILD.bazel').read_text().splitlines())
rows.append(dict(case='generated-producers', count=44))
source = workspace / 'src/Http/Http.Abstractions/src/QueryString.cs'
api = source.with_name('PublicAPI.Unshipped.txt')
original = source.read_text()
original_api = api.read_text()
reference = workspace / 'bazel-bin/src_Http_Http.Abstractions_src_Microsoft.AspNetCore.Http.Abstractions_net10_0.reference/Microsoft.AspNetCore.Http.Abstractions.dll'
digest = lambda: hashlib.sha256(reference.read_bytes()).hexdigest()
baseline = digest()
try:
    needle = 'public readonly struct QueryString : IEquatable<QueryString>\n{'
    assert needle in original
    source.write_text(original.replace(needle, needle + '\n    /// <summary>Qualification API probe.</summary>\n    public bool QualificationProbe => HasValue;\n', 1))
    api.write_text(original_api + '\nMicrosoft.AspNetCore.Http.QueryString.QualificationProbe.get -> bool\n')
    run('api-edit', ['test', target, '--jobs=2', '--build_event_json_file=' + str(out / 'api.bep')])
    events = [json.loads(line) for line in (out / 'api.bep').read_text().splitlines()]
    tests = [e['testResult'] for e in events if 'testResult' in e]
    assert len(tests) == 1 and not tests[0].get('cachedLocally', False)
    assert digest() != baseline
    rows.append(dict(case='api-invalidation', referenceChanged=True, testsExecuted=True))
    source.write_text(original)
    api.write_text(original_api)
    run('api-restored', ['test', target, '--jobs=2'])
    assert digest() == baseline
    source.unlink()
    diagnostic = run('missing-source', ['run', '//:sync', '--', '--check'], success=False)
    assert 'stale' in diagnostic or 'Missing' in diagnostic, diagnostic[-1500:]
    assert generated.read_bytes() == original_generated
finally:
    source.write_text(original)
    api.write_text(original_api)
    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
run('repaired', ['run', '//:sync', '--', '--check'])
(out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
