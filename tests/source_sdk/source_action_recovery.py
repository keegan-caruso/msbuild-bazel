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
        summary = {key: row.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit', 'commandArgs']}
        if row.get('mnemonic') == 'SourceSdkBuild':
            summary['sdkDigests'] = [output['digest']['hash'] for output in row.get('actualOutputs', [])
                                     if output['path'].endswith('/sdk.generated/sdk.tar.gz')]
        result.append(summary)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('seed', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--seed-output-base', type=Path, help='Explicit producer output base to shut down; omit when producer was stopped externally')
    parser.add_argument('--runtime-version', help='Expected runtime version (default: seed SDK major.minor.0)')
    parser.add_argument('--smoke-only', action='store_true',
                        help='Force the runtime test in a fresh workspace and verify the cached SDK output digest')
    parser.add_argument('--download-outputs', choices=['all', 'toplevel', 'minimal'],
                        help='Bazel output download mode for a smoke-only run (default: toplevel)')
    parser.add_argument('--remote-connections', type=int, help='Maximum concurrent connections to the Bazel cache')
    args = parser.parse_args()
    if args.download_outputs and not args.smoke_only:
        parser.error('--download-outputs requires --smoke-only')
    if args.remote_connections is not None and args.remote_connections < 1:
        parser.error('--remote-connections must be positive')
    download = args.download_outputs or ('toplevel' if args.smoke_only else 'all')
    seed, folder = args.seed.resolve(), args.directory.resolve()
    contract = json.loads((seed / 'app-contract.json').read_text())
    runtime_version = args.runtime_version or '.'.join(contract['SdkVersion'].split('.')[:2]) + '.0'
    seed_base = None
    if args.seed_output_base:
        seed_base = args.seed_output_base.resolve(strict=True)
        seed_out = seed / 'bazel-out'
        assert seed_out.is_symlink() and seed_out.resolve(strict=True).is_relative_to(seed_base / 'execroot'), seed_out
        subprocess.run([os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(seed_base),
                        '--ignore_all_rc_files', 'shutdown'], cwd=seed, check=True, timeout=120)
    archives = list((seed / 'bazel-out').rglob('sdk.generated/sdk.tar.gz'))
    assert len(archives) == 1, archives
    expected = digest(archives[0])
    folder.mkdir(parents=True, exist_ok=False)
    workspace = folder / 'workspace'
    shutil.copytree(seed, workspace, copy_function=os.link,
                    ignore=shutil.ignore_patterns('bazel-*', 'MODULE.bazel.lock'))
    reports = []
    cases = [
        ('recover', None),
        ('body-edit', 'System.Console.WriteLine("EDITED_SDK_FROM_SOURCE="+System.Environment.Version); return System.Environment.Version.ToString()=="{runtime_version}" ? 0 : 1;'),
        ('api-edit', 'public class Program { public static int Main() => Verify(System.Environment.Version); public static int Verify(System.Version version) => version.ToString()=="{runtime_version}" ? 0 : 1; }'),
    ]
    for name, source in (cases[:1] if args.smoke_only else cases):
        if source is not None:
            source = source.replace('{runtime_version}', runtime_version)
            temporary = workspace / 'App.cs.tmp'
            temporary.write_text(source)
            temporary.replace(workspace / 'App.cs')
        log = folder / (name + '.execution.json')
        command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m',
                   '--output_base=' + str(folder / 'base'), '--output_user_root=' + str(folder / 'user'),
                   '--ignore_all_rc_files', 'test', '//:smoke', '--jobs=1', '--lockfile_mode=off',
                   '--disk_cache=', '--remote_cache=' + args.cache, '--remote_upload_local_results=false',
                   '--remote_cache_async=false', '--remote_download_outputs=' + download, '--test_output=all',
                   '--execution_log_json_file=' + str(log)]
        if args.smoke_only or source is not None:
            command.append('--nocache_test_results')
        if args.remote_connections:
            command.append('--remote_max_connections=' + str(args.remote_connections))
        started = time.perf_counter()
        with (folder / (name + '.log')).open('w') as output:
            completed = subprocess.run(command, cwd=workspace, stdout=output, stderr=subprocess.STDOUT, timeout=3600)
        elapsed = time.perf_counter() - started
        assert completed.returncode == 0, folder / (name + '.log')
        rows = actions(log)
        source_actions = [r for r in rows if r['mnemonic'] == 'SourceSdkBuild']
        if name == 'recover':
            assert len(source_actions) == 1 and source_actions[0]['cacheHit'], source_actions
            if args.smoke_only:
                assert source_actions[0]['sdkDigests'] == [expected], source_actions
                assert all(row['cacheHit'] for row in rows if row['mnemonic'] != 'TestRunner'), rows
                assert any(row['mnemonic'] == 'TestRunner' and not row['cacheHit'] and
                           row['commandArgs'][0].endswith('/test-setup.sh') for row in rows), rows
                assert 'SDK_FROM_SOURCE=' + runtime_version in (folder / (name + '.log')).read_text().splitlines()
            else:
                assert rows and all(row['cacheHit'] for row in rows), rows
        else:
            assert all(row['cacheHit'] for row in source_actions), source_actions
            assert any(row['mnemonic'] == 'MSBuildGraph' and not row['cacheHit'] for row in rows), rows
            assert any(row['mnemonic'] == 'TestRunner' and not row['cacheHit']
                       and row['commandArgs'][0].endswith('/test-setup.sh') for row in rows), rows
        if download == 'all':
            recovered = list((workspace / 'bazel-out').rglob('sdk.generated/sdk.tar.gz'))
            assert len(recovered) == 1 and digest(recovered[0]) == expected, recovered
        reports.append({'case': name, 'bazelSeconds': elapsed, 'wallSeconds': time.perf_counter() - started,
                        'actions': rows})
        (folder / 'report.json').write_text(json.dumps({'sdkArchiveSha256': expected, 'sdkVersion': contract['SdkVersion'],
                                                        'downloadOutputs': download, 'remoteConnections': args.remote_connections,
                                                        'smokeOnly': args.smoke_only,
                                                        'runtimeVersion': runtime_version, 'stoppedProducerOutputBase': str(seed_base) if seed_base else None, 'runs': reports}, indent=2) + '\n')
        print(name, round(reports[-1]['wallSeconds'], 2), flush=True)


if __name__ == '__main__':
    main()
