"""Fresh download, offline archive-cache recovery, and bad-digest rejection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
a = p.parse_args()
root = a.output.resolve()
root.mkdir(parents=True, exist_ok=False)
source = Path(__file__).parent
bazel = os.environ['RULES_MSBUILD_BAZEL']
lock = json.loads((source / 'native-packages.json').read_text())
results = []
for case in ['download', 'offline-recovery', 'bad-digest']:
    workspace = root / case
    workspace.mkdir()
    shutil.copyfile(source / 'native_packages.bzl', workspace / 'native_packages.bzl')
    data = json.loads(json.dumps(lock))
    if case == 'bad-digest':
        data['packages'][0]['sha256'] = '0' * 64
    (workspace / 'native-packages.json').write_text(json.dumps(data))
    (workspace / 'BUILD.bazel').write_text('')
    (workspace / 'MODULE.bazel').write_text('module(name="native_controls")\nnative_runtime=use_repo_rule("//:native_packages.bzl","native_runtime")\nnative_runtime(name="avalonia_native",lock="//:native-packages.json",include_vnc=True)\n')
    base = root / (case + '-base')
    startup = [bazel, '--output_base=' + str(base), '--ignore_all_rc_files']
    try:
        command = startup + ['fetch', '@avalonia_native//:runtime_files', '--lockfile_mode=off', '--repository_cache=' + str(root / 'repository-cache')]
        if case == 'offline-recovery':
            command += ['--repository_disable_download']
        result = subprocess.run(command, cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (root / (case + '.log')).write_text(result.stdout)
        if case == 'bad-digest':
            assert result.returncode != 0 and 'checksum' in result.stdout.lower(), result.stdout[-2500:]
            results.append(dict(case=case,rejected=True))
        else:
            assert result.returncode == 0, result.stdout[-2500:]
            candidates = list((base / 'external').glob('*+avalonia_native'))
            assert len(candidates) == 1, candidates
            hashes = {r['destination']:hashlib.sha256((candidates[0]/r['destination']).read_bytes()).hexdigest() for r in lock['files']}
            assert hashes == {r['destination']:r['sha256'] for r in lock['files']}
            results.append(dict(case=case,packages=len(lock['packages']),files=len(hashes),hashes=hashes))
    finally:
        subprocess.run(startup + ['shutdown'], cwd=workspace, check=True)
(root / 'report.json').write_text(json.dumps(dict(bazel=subprocess.check_output([bazel,'--version'],text=True).strip(),cases=results),indent=2)+'\n')
