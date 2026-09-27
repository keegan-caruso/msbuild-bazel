"""Seed and recover produced-SDK consumers at a fresh path using an HTTP action cache.

Both workspaces run on the current machine. Fresh output/user roots and an empty
local disk-cache setting separate recovery from local Bazel state. This does not
qualify remote execution or the SDK source-component graph.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('fixture', type=Path)
p.add_argument('directory', type=Path)
p.add_argument('--cache', required=True)
a = p.parse_args()
folder = a.directory.resolve()
folder.mkdir(parents=True, exist_ok=False)
source = a.fixture.resolve() / 'source'
assert (source / 'source-sdk.tar.gz').is_file()
targets = ['//:test', '//scenarios:package_test', '//scenarios:razor_test']
reports = []


def run(name, workspace, seed, forced=False):
    state = 'recover' if forced else name
    command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m',
               '--output_base=' + str(folder / (state + '-base')),
               '--output_user_root=' + str(folder / (state + '-user')), '--ignore_all_rc_files',
               'test', *targets, '--jobs=2', '--lockfile_mode=off', '--disk_cache=',
               '--remote_cache=' + a.cache, '--remote_upload_local_results=' + str(seed).lower(),
               '--remote_accept_cached=' + str(not seed).lower(),
               '--remote_cache_async=false', '--remote_download_outputs=all', '--test_output=all',
               '--execution_log_json_file=' + str(folder / (name + '.execution.json'))]
    if forced:
        command.append('--nocache_test_results')
    started = time.perf_counter()
    with (folder / (name + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=workspace, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    assert result.returncode == 0, str(folder / (name + '.log'))
    data = (folder / (name + '.execution.json')).read_text()
    decoder, actions = json.JSONDecoder(), []
    while data.strip():
        row, end = decoder.raw_decode(data.lstrip())
        data = data.lstrip()[end:]
        action = {key: row.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit']}
        action['command'] = row.get('commandArgs', [''])[0]
        actions.append(action)
    relevant = [r for r in actions if r['mnemonic'] in {
        'SourceSdkArchiveProducer', 'MSBuildRunnerBootstrap', 'MSBuildAssembly',
        'MSBuildGenerate', 'MSBuildNugetExtract', 'DotnetSdkRuntime', 'TestRunner'}]
    if not seed and not forced:
        assert {'SourceSdkArchiveProducer', 'MSBuildRunnerBootstrap', 'MSBuildAssembly', 'TestRunner'} <= {r['mnemonic'] for r in relevant}, relevant
        assert all(r['cacheHit'] for r in actions), actions
    if forced:
        tests = [r for r in relevant if r['mnemonic'] == 'TestRunner' and r['command'].endswith('/test-setup.sh')]
        assert len(tests) == len(targets) and all(not r['cacheHit'] for r in tests), tests
        assert all(r['cacheHit'] for r in relevant if r['mnemonic'] != 'TestRunner'), relevant
    row = {'case': name, 'wallSeconds': time.perf_counter() - started, 'actions': relevant}
    reports.append(row)
    print(name, round(row['wallSeconds'], 2), flush=True)


def hashes(workspace):
    result = {}
    root = workspace / 'bazel-out'
    for path in sorted(root.rglob('*')):
        if path.is_file() and (any(part.endswith(('.reference', '.runtime', '.generated')) for part in path.parts)
                               or path.name == 'dotnet' and path.parent.name == 'artifacts'):
            result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result
    return result


for name in ['seed', 'recover']:
    workspace = folder / name
    shutil.copytree(source, workspace, ignore=shutil.ignore_patterns('bazel-*'))
    (workspace / 'Lib.cs').write_text('public static class Lib { public static int Value() => 1; }')
    run(name, workspace, seed=name == 'seed')
    actual = hashes(workspace)
    if name == 'seed':
        expected = actual
    else:
        assert actual == expected, 'Recovered artifacts differ'
        run('forced-tests', workspace, seed=False, forced=True)
(folder / 'report.json').write_text(json.dumps({'runs': reports, 'hashes': expected}, indent=2) + '\n')
