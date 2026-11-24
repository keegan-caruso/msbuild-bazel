"""Recover a seeded full SDK source action, then test consumer-only edits.

Run after source_action_prepare.py and a successful cache-uploading //:smoke build.
Uses a new workspace and empty Bazel roots on the same Linux machine. Input
archives are hard-linked to conserve disk; edited app files are replaced atomically.
"""
import argparse
import hashlib
import json
import os
import re
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


def actions(path, include_test_details=False):
    data = path.read_text()
    decoder = json.JSONDecoder()
    result = []
    while data.strip():
        row, end = decoder.raw_decode(data.lstrip())
        data = data.lstrip()[end:]
        summary = {key: row.get(key) for key in ['mnemonic', 'targetLabel', 'cacheHit', 'commandArgs']}
        if include_test_details and row.get('mnemonic') == 'TestRunner' and row.get('commandArgs') and \
                row['commandArgs'][0].endswith('/test-setup.sh'):
            summary['metrics'] = row.get('metrics', {})
            summary['runfilesInputs'] = [entry for entry in row.get('inputs', [])
                                         if re.search(r'(?:^|/)smoke\.runfiles/', entry.get('path', ''))]
        if row.get('mnemonic') == 'SourceSdkBuild':
            summary['sdkDigests'] = [output['digest']['hash'] for output in row.get('actualOutputs', [])
                                     if output['path'].endswith('/sdk.generated/sdk.tar.gz')]
        result.append(summary)
    return result


def profile_summary(path):
    """Use Bazel 9.3.2 SpawnRunner's stage span and enclosing test action."""
    data = json.loads(path.read_text())
    events = data.get('traceEvents', []) if isinstance(data, dict) else data
    staging = [event for event in events if event.get('ph') == 'X' and
               event.get('cat') == 'remote output download' and event.get('name') == 'stage remote inputs']
    tests = [event for event in events if event.get('ph') == 'X' and
             event.get('args', {}).get('mnemonic') == 'TestRunner' and
             event.get('args', {}).get('target') == '//:smoke']
    scoped = [event for event in staging if any(
        event.get('tid') == test.get('tid') and test['ts'] <= event['ts'] and
        event['ts'] + event['dur'] <= test['ts'] + test['dur'] for test in tests)]
    return {'path': str(path), 'remoteInputStagingSpanCount': len(staging),
            'remoteInputStagingSpanSeconds': sum(event['dur'] for event in staging) / 1_000_000 if staging else None,
            'testRemoteInputStagingSpanCount': len(scoped),
            'testRemoteInputStagingSpanSeconds': sum(event['dur'] for event in scoped) / 1_000_000 if scoped else None,
            'note': 'Summed spans may overlap. Test attribution requires matching lane and containment; null means unavailable. Not wire traffic.'}


def runfiles_inventory(rows, destination):
    """Inventory logical smoke runfiles paths from the execution log only."""
    logged = {}
    for row in rows:
        if row.get('mnemonic') != 'TestRunner' or not row.get('commandArgs') or not row['commandArgs'][0].endswith('/test-setup.sh'):
            continue
        for entry in row.get('runfilesInputs', []):
            match = re.search(r'(?:^|/)smoke\.runfiles/(.+)$', entry['path'])
            if match:
                logged[match.group(1)] = entry
    entries = [{'path': path, 'logicalBytes': int(entry.get('digest', {}).get('sizeBytes', 0)),
                'sha256': entry.get('digest', {}).get('hash')} for path, entry in sorted(logged.items())]
    frameworks = {}
    for entry in entries:
        match = re.search(r'^(.*?/shared/[^/]+/[^/]+)(?:/|$)', entry['path'])
        if match:
            layout = frameworks.setdefault(match.group(1), {'fileCount': 0, 'logicalBytes': 0})
            layout['fileCount'] += 1
            layout['logicalBytes'] += entry['logicalBytes']
    destination.write_text(json.dumps({'files': entries}, indent=2) + '\n')
    return {'path': str(destination), 'source': 'execution-log', 'available': bool(entries),
            'fileCount': len(entries), 'logicalBytes': sum(entry['logicalBytes'] for entry in entries),
            'frameworkLayouts': frameworks,
            'packedRuntimeArchives': [entry for entry in entries if entry['path'].endswith('/packed_console_runtime.runtime/runtime.tar.zst')]}


def test_execution_seconds(rows):
    durations = [row.get('metrics', {}).get('executionWallTime') for row in rows
                 if row['mnemonic'] == 'TestRunner' and not row['cacheHit'] and
                 row.get('commandArgs') and row['commandArgs'][0].endswith('/test-setup.sh')]
    return sum(float(value.removesuffix('s')) for value in durations) if durations and all(
        value is not None for value in durations) else None


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
    parser.add_argument('--locked', action='store_true', help='Use the producer MODULE.bazel.lock in Bazel error mode')
    parser.add_argument('--profile', action='store_true', help='Retain JSON Bazel traces and summarize staging spans')
    args = parser.parse_args()
    if args.download_outputs and not args.smoke_only:
        parser.error('--download-outputs requires --smoke-only')
    if args.remote_connections is not None and args.remote_connections < 1:
        parser.error('--remote-connections must be positive')
    download = args.download_outputs or ('toplevel' if args.smoke_only else 'all')
    seed, folder = args.seed.resolve(), args.directory.resolve()
    if args.locked and not (seed / 'MODULE.bazel.lock').is_file():
        parser.error('--locked requires a seed MODULE.bazel.lock produced with --lockfile_mode=update')
    lockfile_mode = 'error' if args.locked else 'off'
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
    if args.locked:
        shutil.copyfile(seed / 'MODULE.bazel.lock', workspace / 'MODULE.bazel.lock')
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
                   '--ignore_all_rc_files', 'test', '//:smoke', '--jobs=1', '--lockfile_mode=' + lockfile_mode,
                   '--disk_cache=', '--remote_cache=' + args.cache, '--remote_upload_local_results=false',
                   '--remote_cache_async=false', '--remote_download_outputs=' + download, '--test_output=all',
                   '--execution_log_json_file=' + str(log)]
        profile = folder / (name + '.profile.json')
        if args.profile:
            command += ['--profile=' + str(profile), '--generate_json_trace_profile',
                        '--noslim_profile', '--experimental_profile_include_target_label']
        if args.smoke_only or source is not None:
            command.append('--nocache_test_results')
        if args.remote_connections:
            command.append('--remote_max_connections=' + str(args.remote_connections))
        started = time.perf_counter()
        with (folder / (name + '.log')).open('w') as output:
            completed = subprocess.run(command, cwd=workspace, stdout=output, stderr=subprocess.STDOUT, timeout=3600)
        elapsed = time.perf_counter() - started
        assert completed.returncode == 0, folder / (name + '.log')
        rows = actions(log, include_test_details=True)
        source_actions = [r for r in rows if r['mnemonic'] == 'SourceSdkBuild']
        if name == 'recover':
            assert len(source_actions) == 1 and source_actions[0]['cacheHit'], source_actions
            if args.smoke_only:
                assert source_actions[0]['sdkDigests'] == [expected], source_actions
                assert all(row['cacheHit'] for row in rows if row['mnemonic'] != 'TestRunner'), rows
                assert any(row['mnemonic'] == 'MSBuildGraph' and row['cacheHit'] for row in rows), rows
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
                        'actions': rows, 'testExecutionSeconds': test_execution_seconds(rows),
                        'runfiles': runfiles_inventory(rows, folder / (name + '.runfiles.json'))})
        if args.smoke_only and args.profile:
            inventory = reports[-1]['runfiles']
            layouts = inventory['frameworkLayouts']
            assert inventory['available'], 'Smoke profile requires a runfiles inventory'
            if inventory['packedRuntimeArchives']:
                assert len(inventory['packedRuntimeArchives']) == 1, inventory
                assert not layouts, 'Packed smoke unexpectedly stages an unpacked framework'
            else:
                assert len({path.split('/shared/', 1)[0] for path in layouts}) == 1, layouts
                assert any(path.endswith('/shared/Microsoft.NETCore.App/' + runtime_version) for path in layouts), layouts
        for row in rows:
            row.pop('runfilesInputs', None)
        if args.profile:
            reports[-1]['profile'] = profile_summary(profile)
        (folder / 'report.json').write_text(json.dumps({'sdkArchiveSha256': expected, 'sdkVersion': contract['SdkVersion'],
                                                        'lockfileMode': lockfile_mode, 'downloadOutputs': download, 'remoteConnections': args.remote_connections,
                                                        'smokeOnly': args.smoke_only, 'profile': args.profile,
                                                        'runtimeVersion': runtime_version, 'stoppedProducerOutputBase': str(seed_base) if seed_base else None, 'runs': reports}, indent=2) + '\n')
        print(name, round(reports[-1]['wallSeconds'], 2), flush=True)


if __name__ == '__main__':
    main()
