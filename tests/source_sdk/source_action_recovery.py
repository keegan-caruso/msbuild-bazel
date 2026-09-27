"""Recover a seeded full SDK source action, then test consumer-only edits.

Run after source_action_prepare.py and a successful cache-uploading //:smoke build.
Uses a new workspace and empty Bazel roots on the same Linux machine. Input
archives are hard-linked to conserve disk; edited app files are replaced atomically.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def actions(path):
    data = path.read_text()
    decoder = json.JSONDecoder()
    result = []
    while data.strip():
        row, end = decoder.raw_decode(data.lstrip())
        data = data.lstrip()[end:]
        result.append({key: row.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit', 'commandArgs']})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    seed, folder = args.seed.resolve(), args.directory.resolve()
    archives = list((seed / 'bazel-out').rglob('sdk.generated/sdk.tar.gz'))
    assert len(archives) == 1, archives
    expected = digest(archives[0])
    folder.mkdir(parents=True, exist_ok=False)
    workspace = folder / 'workspace'
    shutil.copytree(seed, workspace, copy_function=os.link,
                    ignore=shutil.ignore_patterns('bazel-*', 'MODULE.bazel.lock'))
    reports = []
    for name, source in [
        ('recover', None),
        ('body-edit', 'System.Console.WriteLine("EDITED_SDK_FROM_SOURCE="+System.Environment.Version); return System.Environment.Version.ToString()=="10.0.0" ? 0 : 1;'),
        ('api-edit', 'public class Program { public static int Main() => Verify(System.Environment.Version); public static int Verify(System.Version version) => version.ToString()=="10.0.0" ? 0 : 1; }'),
    ]:
        if source is not None:
            temporary = workspace / 'App.cs.tmp'
            temporary.write_text(source)
            temporary.replace(workspace / 'App.cs')
        log = folder / (name + '.execution.json')
        command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m',
                   '--output_base=' + str(folder / 'base'), '--output_user_root=' + str(folder / 'user'),
                   '--ignore_all_rc_files', 'test', '//:smoke', '--jobs=1', '--lockfile_mode=off',
                   '--disk_cache=', '--remote_cache=' + args.cache, '--remote_upload_local_results=false',
                   '--remote_cache_async=false', '--remote_download_outputs=all', '--test_output=all',
                   '--execution_log_json_file=' + str(log)]
        started = time.perf_counter()
        with (folder / (name + '.log')).open('w') as output:
            completed = subprocess.run(command, cwd=workspace, stdout=output, stderr=subprocess.STDOUT, timeout=3600)
        assert completed.returncode == 0, folder / (name + '.log')
        rows = actions(log)
        source_actions = [r for r in rows if r['mnemonic'] == 'SourceSdkBuild']
        if name == 'recover':
            assert len(source_actions) == 1 and source_actions[0]['cacheHit'], source_actions
            assert rows and all(row['cacheHit'] for row in rows), rows
        else:
            assert all(row['cacheHit'] for row in source_actions), source_actions
            assert any(row['mnemonic'] == 'MSBuildAssembly' and not row['cacheHit'] for row in rows), rows
            assert any(row['mnemonic'] == 'TestRunner' and not row['cacheHit']
                       and row['commandArgs'][0].endswith('/test-setup.sh') for row in rows), rows
        recovered = list((workspace / 'bazel-out').rglob('sdk.generated/sdk.tar.gz'))
        assert len(recovered) == 1 and digest(recovered[0]) == expected, recovered
        reports.append({'case': name, 'wallSeconds': time.perf_counter() - started, 'actions': rows})
        (folder / 'report.json').write_text(json.dumps({'sdkArchiveSha256': expected, 'runs': reports}, indent=2) + '\n')
        print(name, round(reports[-1]['wallSeconds'], 2), flush=True)


if __name__ == '__main__':
    main()
