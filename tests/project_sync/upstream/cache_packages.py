"""Record declared archive origins, then independently reacquire and hash-check them."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('mode', choices=['record', 'acquire'])
p.add_argument('workspace', type=Path)
p.add_argument('manifest', type=Path)
p.add_argument('--package-root', type=Path, action='append', default=[])
a = p.parse_args()
w = a.workspace.resolve()
began = time.monotonic()
if a.mode == 'record':
    rows = []
    for line in (w / 'BUILD.bazel').read_text().splitlines():
        if not line.startswith('msbuild_nuget_package('):
            continue
        node = ast.parse(line).body[0].value
        d = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        identity, version = d['package_id'].lower(), d['version'].lower()
        sources = []
        for root in a.package_root:
            metadata = root / identity / version / '.nupkg.metadata'
            if metadata.exists():
                sources.append(json.loads(metadata.read_text())['source'])
        if identity == 'microsoft.testplatform.cli':
            sources.append('https://api.nuget.org/v3/index.json')
        assert sources, (identity, version)
        digest = hashlib.sha256((w / d['archive']).read_bytes()).hexdigest()
        assert digest == d['archive_sha256']
        rows.append(dict(id=identity, version=version, archive=d['archive'], sha256=digest, source=sources[0]))
    assert rows
    a.manifest.write_text(json.dumps(rows, indent=2) + '\n')
else:
    rows = json.loads(a.manifest.read_text())
    feeds = {}
    for source in sorted({r['source'] for r in rows}):
        index = json.loads(subprocess.check_output(['curl', '-fsSL', '--retry', '3', '--max-time', '90', source]))
        feeds[source] = next(r['@id'] for r in index['resources'] if str(r['@type']).startswith('PackageBaseAddress/'))
    def acquire(row):
        path = w / row['archive']
        assert path.resolve().is_relative_to(w)
        assert not path.exists(), 'Consumer archive must be acquired from the feed'
        url = feeds[row['source']].rstrip('/') + '/' + row['id'] + '/' + row['version'] + '/' + row['id'] + '.' + row['version'] + '.nupkg'
        data = subprocess.check_output(['curl', '-fsSL', '--retry', '3', '--max-time', '180', url])
        assert hashlib.sha256(data).hexdigest() == row['sha256'], row['archive']
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return len(data)
    with ThreadPoolExecutor(max_workers=4) as pool:
        sizes = list(pool.map(acquire, rows))
    a.manifest.with_suffix('.acquired.json').write_text(json.dumps(dict(archives=len(rows), bytes=sum(sizes), seconds=round(time.monotonic() - began, 3), allHashesMatch=True), indent=2) + '\n')
    print('acquired', len(rows), 'archives', sum(sizes), 'bytes', flush=True)
