"""Hash freshly executed Orchard outputs; invoke twice at different checkout paths.

Requires full_graph.py preparation. Pass a new output base for each invocation;
local and remote action caches are disabled. Compare the resulting manifests.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

source, evidence, base = map(lambda p: Path(p).resolve(), sys.argv[1:4])
assert not base.exists(), 'Use a fresh output base'
evidence.mkdir(parents=True, exist_ok=True)
bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(base), '--ignore_all_rc_files']
flags = ['--repository_cache=/tmp/repository-cache', '--disk_cache=', '--remote_cache=',
         '--jobs=4', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=2',
         '--noshow_progress', '--color=no', '--curses=no']
try:
    started = time.perf_counter()
    with (evidence/'build.log').open('w') as log:
        subprocess.run(bazel+['build', '//:OrchardCore.Cms.Web']+flags, cwd=source,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    seconds = time.perf_counter()-started
    log = (evidence/'build.log').read_text()
    workers = sum(map(int, re.findall(r'(\d+) worker', log)))
    assert workers == 202 and not re.search(r'\d+ (?:remote|disk) cache hit', log), log[-2000:]
    output = source/'bazel-bin'
    hashes = {}
    for tree in sorted(output.iterdir()):
        if tree.name.endswith(('.reference', '.runtime')):
            for path in sorted(tree.rglob('*')):
                if path.is_file():
                    with path.open('rb') as stream:
                        digest = hashlib.sha256()
                        for chunk in iter(lambda: stream.read(1024*1024), b''):
                            digest.update(chunk)
                        hashes[str(path.relative_to(output))] = digest.hexdigest()
    assert sum('.reference/' in name and name.endswith('.dll') for name in hashes) == 202
    (evidence/'hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
    (evidence/'result.json').write_text(json.dumps(dict(seconds=seconds, workerActions=workers,
        referenceAssemblies=202, publishedFiles=len(hashes)), indent=2)+'\n')
    print((evidence/'result.json').read_text(), flush=True)
finally:
    subprocess.run(bazel+['shutdown'], cwd=source, check=True)
