"""Qualify compiler reuse on prepared, pinned Orchard/ASP.NET fixtures.

Setup is deliberately separate. Run through a child-reaping init in containers.
A fresh output base measures cold compilation; --cache seeds an HTTP cache.
--recovery requires only remote hits and records hashes for producer comparison.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.measure import command as timed_command
import shutil
import subprocess
import uuid

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('kind', choices=['orchard', 'aspnetcore'])
for name in ['workspace', 'base', 'report']:
    p.add_argument(name, type=Path)
p.add_argument('--cache', default='')
p.add_argument('--recovery', action='store_true')
p.add_argument('--expect-hashes', type=Path, help='Require exact declared reference/runtime hashes from the producer')
p.add_argument('--workers', type=int, default=2)
p.add_argument('--edits', action='store_true')
p.add_argument('--memory-limit-mb', type=int, default=0)
p.add_argument('--trim', action='store_true', help='Run Linux fstrim / outside each measurement (requires permission)')
a = p.parse_args()
if a.workers < 1 or a.memory_limit_mb < 0:
    p.error('workers must be positive and the memory limit nonnegative')
w, base, out = a.workspace.resolve(), a.base.resolve(), a.report.resolve()
assert not base.exists() and not out.exists(), 'Use fresh output and evidence directories'
assert not a.recovery or a.cache and not a.edits
out.mkdir(parents=True)
orchard = a.kind == 'orchard'
target = '//:OrchardCore.Cms.Web' if orchard else '//upstream:benchmark'
startup = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1024m', '--output_base='+str(base), '--ignore_all_rc_files']
flags = ['--jobs=4', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly='+str(a.workers), '--disk_cache=', '--remote_cache='+a.cache, '--remote_download_outputs=all', '--remote_upload_local_results='+str(bool(a.cache) and not a.recovery).lower()]
if a.memory_limit_mb:
    flags += ['--experimental_total_worker_memory_limit_mb='+str(a.memory_limit_mb), '--experimental_shrink_worker_pool', '--experimental_worker_metrics_poll_interval=1s']
if not a.recovery:
    flags += ['--remote_accept_cached=false']
rows = []
sdk = subprocess.check_output([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), '--version'], cwd=w, text=True).strip()
bazel_version = subprocess.check_output([os.environ['RULES_MSBUILD_BAZEL'], '--version'], cwd=w, text=True).strip()
assert sdk == '10.0.400' and bazel_version == 'bazel 9.2.0', (sdk, bazel_version)
runner = Path(__file__).resolve().parents[2]/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'
report = dict(kind=a.kind, workers=a.workers, memoryLimitMb=a.memory_limit_mb, filesystemTrimOutsideTiming=a.trim, sdk=sdk, bazel=bazel_version, runnerSha256=hashlib.sha256(runner.read_bytes()).hexdigest(), rows=rows)

def save():
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')

def build(case):
    command = startup+['build', target, '--build_event_json_file='+str(out/(case+'.bep'))]+flags
    result,wall=timed_command(command,w,out/(case+'.log'),timeout=1200)
    row = dict(case=case, seconds=wall, exitCode=result.returncode, command=command)
    rows.append(row); save(); result.check_returncode()
    if a.trim:
        subprocess.run(['fstrim', '/'], check=True)
    metrics = next(e['buildMetrics'] for e in map(json.loads, (out/(case+'.bep')).read_text().splitlines()) if 'buildMetrics' in e)
    row['runners'] = {r['name']: int(r['count']) for r in metrics['actionSummary'].get('runnerCount', [])}
    save(); print(json.dumps({k: row[k] for k in ['case', 'seconds', 'runners']}), flush=True)
    return row

def hashes(patterns):
    root = w/'bazel-bin' if orchard else w/'bazel-bin/upstream'
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for pattern in patterns for tree in sorted(root.glob(pattern))
            for f in sorted(tree.rglob('*')) if f.is_file() and not f.name.endswith('.params')}

source = w/('src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs' if orchard else 'upstream/src/ObjectPool/src/DefaultObjectPool.cs')
saved = source.read_bytes()
api_baseline = None if orchard else source.with_name('PublicAPI.Unshipped.txt')
saved_api = None if api_baseline is None else api_baseline.read_bytes()
try:
    row = build('recovery' if a.recovery else 'seed' if a.cache else 'cold')
    if a.recovery:
        assert row['runners'].get('remote cache hit') == (489 if orchard else 578), row
        assert not row['runners'].get('worker') and not row['runners'].get('linux-sandbox'), row
    else:
        assert row['runners'].get('worker') == (202 if orchard else 278), row
    original = hashes(['*.reference', '*.runtime'])
    (out/'hashes.json').write_text(json.dumps(original, indent=2)+'\n')
    assert original
    if a.expect_hashes is not None:
        assert original == json.loads(a.expect_hashes.read_text()), 'Producer/consumer output hashes differ'
        report['outputParity'] = True
    if a.edits:
        public = hashes(['*.reference'])
        root = w/'bazel-bin' if orchard else w/'bazel-bin/upstream'
        for name in public:
            copy = out/'original-references'/name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root/name, copy)
        assert not build('noop')['runners'].get('worker')
        nonce = uuid.uuid4().hex
        old = b'string Description => null;' if orchard else b'Environment.ProcessorCount * 2'
        changed = ('string Description => "'+nonce+'";').encode() if orchard else b'Environment.ProcessorCount * 3'
        assert saved.count(old) == 1
        source.write_bytes(saved.replace(old, changed))
        body = build('body')
        assert hashes(['*.reference']) == public, 'Body edit changed reference bytes'
        assert hashes(['*.runtime']) != {k: v for k, v in original.items() if '.runtime/' in k}
        assembly = 'OrchardCore.Abstractions.dll' if orchard else 'Microsoft.Extensions.ObjectPool.dll'
        expected = sum(Path(name).name == assembly for name in public)
        assert expected and body['runners'].get('worker') == expected, body
        source.write_bytes(saved); build('restore-body')
        anchor = b'public class NotFoundManifestInfo : IManifestInfo\n{' if orchard else b'public class DefaultObjectPool<T> : ObjectPool<T> where T : class\n{'
        assert saved.count(anchor) == 1
        member = b'\n    /// <summary>Compiler reuse invalidation control.</summary>\n    public const int CompilerReuseProbe = 73;\n'
        source.write_bytes(saved.replace(anchor, anchor+member))
        if api_baseline is not None:
            api_baseline.write_bytes(saved_api+b'const Microsoft.Extensions.ObjectPool.DefaultObjectPool<T>.CompilerReuseProbe = 73 -> int\n')
        api = build('api')
        assert hashes(['*.reference']) != public
        assert api['runners'].get('worker', 0) > body['runners']['worker'], api
        source.write_bytes(saved)
        if api_baseline is not None:
            api_baseline.write_bytes(saved_api)
        build('restore-api')
        restored = hashes(['*.reference'])
        assert restored.keys() == public.keys()
        changed_references = [name for name in public if restored[name] != public[name]]
        report['restoredReferenceDifferences'] = changed_references
        # Orchard's upstream generators emit random interceptor names and
        # physical paths. Recompilation is not a bitwise-parity contract there.
        # The edited leaf must restore exactly; cache recovery checks all bytes.
        assert all(restored[name] == digest for name, digest in public.items() if Path(name).name == assembly)
        if not orchard:
            assert not changed_references, changed_references
        report['editControlsPassed'] = True
    save()
finally:
    source.write_bytes(saved)
    if api_baseline is not None:
        api_baseline.write_bytes(saved_api)
    report['sourceRestored'] = True
    save()
    subprocess.run(startup+['shutdown'], cwd=w, check=True, timeout=90)
