"""Measure three unique body/API edits over an already-built managed-root baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import uuid

p = argparse.ArgumentParser(description=__doc__)
for name in ['workspace', 'selection', 'base', 'report']:
    p.add_argument(name, type=Path)
a = p.parse_args()
w, out = a.workspace.resolve(), a.report.resolve()
out.mkdir(parents=True, exist_ok=False)
body = w/'upstream/src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'
api = w/'upstream/src/libraries/System.IO.Pipelines/ref/System.IO.Pipelines.cs'
saved, saved_api = body.read_bytes(), api.read_bytes()
old = b'UseSynchronizationContext = useSynchronizationContext;'
body_class, api_class = b'public class PipeOptions\n    {', b'public partial class PipeOptions\n    {'
assert saved.count(old) == saved.count(body_class) == saved_api.count(api_class) == 1
nonce = uuid.uuid4().hex
reference = w/'bazel-bin/upstream/src_libraries_System.IO.Pipelines_ref_System.IO.Pipelines_net10.0.reference/System.IO.Pipelines.dll'
implementation = w/'bazel-bin/upstream/src_libraries_System.IO.Pipelines_src_System.IO.Pipelines_net10.0.runtime/System.IO.Pipelines.dll'
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def run(name, success=True):
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('managed_timing.py')), str(w), str(a.selection), str(a.base), str(out/name), '--case', 'warm'])
    assert (result.returncode == 0) == success, (name, result.returncode)
    r = json.loads((out/name/'report.json').read_text())
    r['sample'] = name
    records.append(r)
    return r
records = []
try:
    run('prime')
    original, public = digest(implementation), digest(reference)
    for kind in ['body', 'api']:
        for i in range(3):
            if kind == 'body':
                row = run('noop-'+str(i))
                assert not row['runners'].get('worker'), row['runners']
                body.write_bytes(saved.replace(old, old+(' GC.KeepAlive("'+nonce+str(i)+'");').encode()))
            else:
                member = ('\n        /// <summary>Benchmark invalidation control.</summary>\n        public const int BenchmarkProbe = '+str(int(nonce[:6], 16)+i)+';').encode()
                body.write_bytes(saved.replace(body_class, body_class+member))
                api.write_bytes(saved_api.replace(api_class, api_class+member))
            row = run(kind+'-'+str(i))
            assert row['runners'].get('worker', 0) > 0, 'Edit did not execute a compiler action'
            assert (digest(reference) == public) == (kind == 'body'), 'Unexpected reference invalidation'
            assert digest(implementation) != original, 'Implementation did not change'
        body.write_bytes(saved)
        api.write_bytes(saved_api)
        run('restore-'+kind)
        assert digest(reference) == public and digest(implementation) == original, 'Restored bytes differ'
    body.write_bytes(saved + b'\n#error Intentional compiler recovery control\n')
    run('compile-error', success=False)
    assert 'error CS1029' in (out/'compile-error/build.log').read_text()
    body.write_bytes(saved.replace(old, old+(' GC.KeepAlive("recovery-'+nonce+'");').encode()))
    recovered = run('compile-after-error')
    assert recovered['runners'].get('worker', 0) > 0
    assert digest(reference) == public and digest(implementation) != original
    body.write_bytes(saved)
    run('restore-after-error')
    assert digest(reference) == public and digest(implementation) == original
finally:
    body.write_bytes(saved)
    api.write_bytes(saved_api)
summary = {kind: dict(samples=[r['wallSeconds'] for r in records if r['sample'].startswith(kind+'-')], median=statistics.median(r['wallSeconds'] for r in records if r['sample'].startswith(kind+'-'))) for kind in ['noop', 'body', 'api']}
(out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary), flush=True)
