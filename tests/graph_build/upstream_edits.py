"""Compare reviewed upstream edits with warm raw graph MSBuild in one owned workspace."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from qualify import DOTNET, ENV, RUNNER, SDK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='disposable staged graph workspace')
    parser.add_argument('contract', type=Path)
    parser.add_argument('cache', type=Path)
    parser.add_argument('edits', type=Path, help='JSON array: name, path, before, after; each replacement must occur once')
    parser.add_argument('results', type=Path)
    parser.add_argument('--samples', type=int, default=1)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--runner', type=Path, default=RUNNER, help='Use a separately built candidate without changing the baseline runner')
    parser.add_argument('--copy-mode', choices=['copy', 'clone'], default=ENV.get('RULES_MSBUILD_GRAPH_COPY_MODE', 'copy'))
    parser.add_argument('--raw-state', choices=['warm', 'clean'], default='warm')
    parser.add_argument('--cache-state', choices=['local', 'empty', 'remote'], default='local')
    parser.add_argument('--raw-restore', action='store_true')
    parser.add_argument('--package-state', choices=['retained', 'fresh'], default='retained',
                        help='Package expansion state for graph runs; fresh models a new Bazel action workspace')
    args = parser.parse_args()
    assert args.samples > 0
    ENV['RULES_MSBUILD_GRAPH_COPY_MODE'] = args.copy_mode
    runner_digest = hashlib.sha256(args.runner.read_bytes()).hexdigest()
    if args.profile:
        ENV['RULES_MSBUILD_GRAPH_PROFILE'] = '1'
    if args.cache_state == 'remote':
        assert ENV.get('RULES_MSBUILD_PROJECT_CACHE_URL'), 'Remote recovery requires an explicit cache endpoint'
    root = args.workspace.resolve()
    contract = json.loads(args.contract.read_text())
    args.results.mkdir(parents=True, exist_ok=True)
    (args.results / "contract.json").write_bytes(args.contract.read_bytes())
    (args.results / "edits.json").write_bytes(args.edits.read_bytes())
    declarations = [item for project in contract['Projects'].values()
                    for item in [project] + project.get('Configurations', [])]
    directories = {root / path for item in declarations for path in item['OutputDirectories']}
    files = {root / path for item in declarations for path in item.get('OutputFiles') or []}
    assert all(path.resolve().is_relative_to(root) and path.resolve() != root for path in directories | files)
    environment = dict(ENV, DOTNET_HOST_PATH=str(DOTNET), NUGET_PACKAGES=str(root / '.nuget'), MSBUILDDISABLENODEREUSE='1')
    raw = [DOTNET, 'msbuild', root / contract['Entry'], '-graphBuild', '-m:4', '-t:Build', '-nologo',
           '-p:UseSharedCompilation=false', f'-p:NetCoreSdkRoot={SDK}/sdk/{contract["SdkVersion"]}',
           f'-p:PathMap={root}=/_/workspace%2C{SDK}=/_/sdk']
    raw += [f'-p:{key}={value}' for key, value in contract['Properties'].items()]
    declared_inputs = set(contract['SharedInputs']) | {path for item in declarations for path in item['Inputs']}
    rows = []

    def execute(command, label):
        start = time.monotonic()
        with (args.results / (label + '.log')).open('w') as log:
            result = subprocess.run(list(map(str, command)), cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
        elapsed = time.monotonic() - start
        assert result.returncode == 0, f'{label} failed; see {args.results / (label + ".log")}'
        return elapsed

    def clear(clear_packages=False):
        if clear_packages:
            packages = root / '.nuget'
            assert not packages.is_symlink(), 'Refusing to clear a linked package directory'
            shutil.rmtree(packages, ignore_errors=True)
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)
        for file in files:
            file.unlink(missing_ok=True)

    def snapshot():
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files | {p for directory in directories for p in directory.rglob('*')}
                if path.is_file() and path.suffix in ('.dll', '.pdb', '.json', '.xml', '.trie', '.resources')}

    def cached(label):
        clear(clear_packages=args.package_state == 'fresh')
        report = (args.results / (label + '.json')).resolve()
        args.cache.mkdir(parents=True, exist_ok=True)
        # Every fresh-cache run owns its own child directory; never delete a caller's cache.
        with tempfile.TemporaryDirectory(prefix='consumer-', dir=args.cache) as fresh:
            selected_cache = args.cache.resolve() if args.cache_state == 'local' else Path(fresh)
            command = [DOTNET, args.runner.resolve(), 'action', root, args.contract.resolve(), report, selected_cache]
            if args.cache_state == 'empty':
                command += ['Build', 'no-read']
            elapsed = execute(command, label)
        return dict(json.loads(report.read_text()), wallSeconds=elapsed)

    edits = json.loads(args.edits.read_text())
    if args.only:
        assert set(args.only) <= {edit['name'] for edit in edits}
        edits = [edit for edit in edits if edit['name'] in args.only]
    expanded = []
    for sample in range(args.samples):
        for edit in edits:
            item = dict(edit)
            if args.samples > 1:
                assert '${sample}' in item.get('sampleAfter', ''), 'Repeated samples need distinct edits'
                item['after'] = item['sampleAfter'].replace('${sample}', str(sample))
                item['name'] += '-' + str(sample)
            expanded.append(item)
    for edit in expanded:
        assert edit['path'] in declared_inputs, 'Edit must be a declared input: ' + edit['path']
        path = root / edit['path']
        assert path.resolve().is_relative_to(root)
        original = path.read_bytes()
        before, after = edit['before'].encode(), edit['after'].encode()
        assert original.count(before) == 1 and before != after, edit['name']
        try:
            cached(edit['name'] + '-baseline')
            # Normalize the raw engine's incremental state before measuring the edit.
            execute(raw, edit['name'] + '-raw-warmup')
            path.write_bytes(original.replace(before, after))
            if args.raw_state == 'clean':
                clear()
            raw_restore_seconds = 0.0
            if args.raw_restore:
                for index, entry in enumerate(contract.get('Entries') or [contract['Entry']]):
                    command = [DOTNET, 'restore', root / entry, '--configfile', root / '.package-source/NuGet.Config',
                               '--source', root / '.package-source', '--packages', root / '.nuget', '-p:NuGetAudit=false',
                               f'-p:NetCoreSdkRoot={SDK}/sdk/{contract["SdkVersion"]}', '-p:RestoreFallbackFolders=',
                               '-p:RestoreAdditionalProjectSources=', '-p:RestoreAdditionalProjectFallbackFolders=']
                    command += [f'-p:{key}={value}' for key, value in contract['Properties'].items() if key.lower() != 'targetframework']
                    raw_restore_seconds += execute(command, edit['name'] + '-raw-restore-' + str(index))
            raw_seconds = execute(raw, edit['name'] + '-raw')
            raw_outputs = snapshot()
            raw_json = {path: (root / path).read_text() for path in raw_outputs if path.endswith('.json')}
            path.write_bytes(original)
            cached(edit['name'] + '-baseline-replay')
            path.write_bytes(original.replace(before, after))
            measured = cached(edit['name'] + '-cached')
            outputs = snapshot()
            row = dict(name=edit['name'], rawState=args.raw_state, cacheState=args.cache_state,
                       runnerSha256=runner_digest, copyMode=args.copy_mode, packageState=args.package_state,
                       rawRestoreSeconds=raw_restore_seconds if args.raw_restore else None,
                       rawEndToEndSeconds=raw_seconds + raw_restore_seconds if args.raw_restore else None,
                       rawBuildSeconds=raw_seconds, cached=measured,
                       missing=sorted(raw_outputs.keys() - outputs.keys()), extra=sorted(outputs.keys() - raw_outputs.keys()),
                       changed=sorted(p for p in outputs.keys() & raw_outputs.keys() if outputs[p] != raw_outputs[p]))
            row['jsonDifferences'] = {path: {'raw': raw_json[path], 'cached': (root / path).read_text()}
                                      for path in row['changed'] if path.endswith('.json')}
            rows.append(row)
            (args.results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps(dict(name=row['name'], rawBuildSeconds=raw_seconds, cached=measured,
                                  missing=len(row['missing']), extra=len(row['extra']), changed=len(row['changed']))), flush=True)
        finally:
            path.write_bytes(original)
    # Warm raw and fresh recovery are different lanes; restore is reported explicitly.


if __name__ == '__main__':
    main()
