"""Measure source-component body/API edits and fresh-workspace remote recovery."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

from inventory import digest
from source_action_recovery import actions


def edit_archive(archive, code):
    temporary = archive.with_suffix('.tmp')
    target = 'src/command-line-api/src/System.CommandLine/RootCommand.cs'
    found = False
    with tarfile.open(archive) as original, tarfile.open(temporary, 'w') as output:
        for entry in original:
            if entry.name == target:
                data = code.encode('utf-8')
                entry.size = len(data)
                output.addfile(entry, io.BytesIO(data))
                found = True
            else:
                output.addfile(entry, original.extractfile(entry) if entry.isfile() else None)
    assert found, target
    temporary.replace(archive)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    workspace, folder = args.workspace.resolve(), args.directory.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    archive = workspace / 'command-line-api.tar'
    with tarfile.open(archive) as source:
        original = source.extractfile('src/command-line-api/src/System.CommandLine/RootCommand.cs').read().decode('utf-8')
    producer_hashes = {name: digest(workspace / 'bazel-bin' / (name + '.generated/component.tar'))
                       for name in ['source-build-reference-packages', 'arcade']}
    reports = []

    def run(name, directory, expected, recovery=False):
        log = folder / (name + '.execution.json')
        base = folder / 'recovery-base' if recovery else args.output_base.resolve()
        command = [os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m', '--output_base=' + str(base)]
        if recovery:
            command.append('--output_user_root=' + str(folder / 'recovery-user'))
        command.extend(['--ignore_all_rc_files', 'test', '//:consumer', '--jobs=1', '--lockfile_mode=off', '--disk_cache=',
                        '--remote_cache=' + args.cache, '--remote_upload_local_results=' + str(not recovery).lower(),
                        '--remote_cache_async=false', '--remote_download_outputs=all', '--test_output=all',
                        '--execution_log_json_file=' + str(log)])
        started = time.perf_counter()
        with (folder / (name + '.log')).open('w') as output:
            result = subprocess.run(command, cwd=directory, stdout=output, stderr=subprocess.STDOUT, timeout=1800)
        assert result.returncode == expected, folder / (name + '.log')
        rows = actions(log)
        built = [row['targetLabel'] for row in rows if row['mnemonic'] == 'SourceComponentBuild' and not row['cacheHit']]
        if name in {'body-edit', 'api-edit'}:
            assert built == ['//:command-line-api'], built
        if recovery:
            components = [row for row in rows if row['mnemonic'] == 'SourceComponentBuild']
            assert len(components) == 3 and all(row['cacheHit'] for row in rows), rows
        for producer, expected_hash in producer_hashes.items():
            assert digest(directory / 'bazel-bin' / (producer + '.generated/component.tar')) == expected_hash, producer
        hashes = {component: digest(directory / 'bazel-bin' / (component + '.generated/component.tar'))
                  for component in [*producer_hashes, 'command-line-api']}
        if recovery:
            assert hashes == reports[-1]['outputHashes'], hashes
        reports.append({'case': name, 'exitCode': result.returncode, 'wallSeconds': time.perf_counter() - started, 'actions': rows, 'outputHashes': hashes})
        (folder / 'report.json').write_text(json.dumps({'runs': reports, 'unchangedProducerHashes': producer_hashes}, indent=2) + '\n')
        print(name, result.returncode, round(reports[-1]['wallSeconds'], 2), flush=True)

    run('baseline', workspace, 0)
    body = original.replace('Options.Add(new VersionOption());', '// Body-edit probe omits the default version option.')
    assert body != original
    edit_archive(archive, body)
    run('body-edit', workspace, 3)
    marker = '        /// <summary>\n        /// The path to the currently running executable.'
    api = original.replace(marker, '        /// <summary>Identifies the API-edit qualification.</summary>\n        public int QualificationMarker => 7;\n\n' + marker)
    assert api != original
    edit_archive(archive, api)
    (workspace / 'App.cs').write_text('var command = new System.CommandLine.RootCommand("qualification"); return command.QualificationMarker == 7 && command.Options.Count == 2 ? 0 : 1;')
    run('api-edit', workspace, 0)
    recovery = folder / 'recovery'
    shutil.copytree(workspace, recovery, copy_function=os.link, ignore=shutil.ignore_patterns('bazel-*', 'MODULE.bazel.lock'))
    run('remote-recovery', recovery, 0, recovery=True)


if __name__ == '__main__':
    main()
