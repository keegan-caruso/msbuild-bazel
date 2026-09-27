"""Check consumer edits and fresh remote recovery of a component-built SDK.

Run after preparing a workspace with ``--through sdk --sdk-consumer`` and
seeding its complete component graph in the selected HTTP action cache.
The generated workspace is disposable: this probe edits its library and app.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from source_action_recovery import actions, digest


def sdk_digest(workspace):
    bundles = list((workspace / 'bazel-out').glob('*-exec/bin/sdk.generated/component.tar'))
    assert len(bundles) == 1, bundles
    return digest(bundles[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    workspace, folder = args.workspace.resolve(), args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    expected_sdk = sdk_digest(workspace)
    reports = []

    def run(name, cwd, expected, recovery=False, forced=False):
        log = folder / (name + '.execution.json')
        base = folder / 'recovery-base' if recovery else args.output_base.resolve()
        command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m',
                   '--output_base=' + str(base)]
        if recovery:
            command.append('--output_user_root=' + str(folder / 'recovery-user'))
        command.extend(['--ignore_all_rc_files', 'test', '//:smoke', '--jobs=1',
                        '--lockfile_mode=off', '--disk_cache=', '--remote_cache=' + args.cache,
                        '--remote_upload_local_results=' + str(not recovery).lower(),
                        '--remote_cache_async=false', '--remote_download_outputs=all',
                        '--test_output=all', '--execution_log_json_file=' + str(log)])
        if forced:
            command.append('--nocache_test_results')
        started = time.perf_counter()
        with (folder / (name + '.log')).open('w') as output:
            result = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, timeout=3600)
        assert result.returncode == expected, folder / (name + '.log')
        rows = actions(log)
        producers = [row for row in rows if row['mnemonic'] == 'SourceComponentBuild']
        assert all(row['cacheHit'] for row in producers), producers
        if recovery and not forced:
            assert len(producers) == 22, producers
            assert rows and all(row['cacheHit'] for row in rows), rows
        if forced:
            tests = [row for row in rows if row['mnemonic'] == 'TestRunner'
                     and row['commandArgs'] and row['commandArgs'][0].endswith('/test-setup.sh')]
            assert tests and all(not row['cacheHit'] for row in tests), tests
            assert all(row['cacheHit'] for row in rows if row not in tests), rows
        assert sdk_digest(cwd) == expected_sdk
        reports.append({'case': name, 'wallSeconds': round(time.perf_counter() - started, 2),
                        'exitCode': result.returncode, 'actions': rows})
        (folder / 'report.json').write_text(json.dumps({'sdkBundleSha256': expected_sdk,
                                                       'runs': reports}, indent=2) + '\n')
        print(name, result.returncode, reports[-1]['wallSeconds'], flush=True)

    library, app = workspace / 'SdkLib.cs', workspace / 'SdkSmoke.cs'
    run('baseline', workspace, 0)
    library.write_text('public static class SdkLib { public static int Value() => 2; }')
    run('body-edit', workspace, 3)
    library.write_text('public static class SdkLib { public static int Value(int required) => required; }')
    run('api-edit-break', workspace, 1)
    source = app.read_text()
    assert 'SdkLib.Value()==1' in source
    app.write_text(source.replace('SdkLib.Value()==1', 'SdkLib.Value(1)==1'))
    run('api-edit-fixed', workspace, 0)
    recovered = folder / 'recovery'
    shutil.copytree(workspace, recovered, copy_function=os.link,
                    ignore=shutil.ignore_patterns('bazel-*', 'MODULE.bazel.lock'))
    run('remote-recovery', recovered, 0, recovery=True)
    run('forced-tests', recovered, 0, recovery=True, forced=True)


if __name__ == '__main__':
    main()
