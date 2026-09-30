"""Compare reviewed upstream edits with warm raw graph MSBuild in one owned workspace."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from qualify import DOTNET, ENV, RUNNER, SDK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='disposable staged graph workspace')
    parser.add_argument('contract', type=Path)
    parser.add_argument('cache', type=Path)
    parser.add_argument('edits', type=Path, help='JSON array: name, path, before, after; each replacement must occur once')
    parser.add_argument('results', type=Path)
    args = parser.parse_args()
    root = args.workspace.resolve()
    contract = json.loads(args.contract.read_text())
    args.results.mkdir(parents=True, exist_ok=True)
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

    def clear():
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)
        for file in files:
            file.unlink(missing_ok=True)

    def snapshot():
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files | {p for directory in directories for p in directory.rglob('*')}
                if path.is_file() and path.suffix in ('.dll', '.pdb', '.json', '.xml', '.trie', '.resources')}

    def cached(label):
        clear()
        report = (args.results / (label + '.json')).resolve()
        elapsed = execute([DOTNET, RUNNER, 'action', root, args.contract.resolve(), report, args.cache.resolve()], label)
        return dict(json.loads(report.read_text()), wallSeconds=elapsed)

    for edit in json.loads(args.edits.read_text()):
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
            raw_seconds = execute(raw, edit['name'] + '-raw')
            raw_outputs = snapshot()
            path.write_bytes(original)
            cached(edit['name'] + '-baseline-replay')
            path.write_bytes(original.replace(before, after))
            measured = cached(edit['name'] + '-cached')
            outputs = snapshot()
            row = dict(name=edit['name'], rawBuildSeconds=raw_seconds, cached=measured,
                       missing=sorted(raw_outputs.keys() - outputs.keys()), extra=sorted(outputs.keys() - raw_outputs.keys()),
                       changed=sorted(p for p in outputs.keys() & raw_outputs.keys() if outputs[p] != raw_outputs[p]))
            rows.append(row)
            (args.results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps(dict(name=row['name'], rawBuildSeconds=raw_seconds, cached=measured,
                                  missing=len(row['missing']), extra=len(row['extra']), changed=len(row['changed']))), flush=True)
        finally:
            path.write_bytes(original)
    # Raw timing excludes Restore; cached timing includes offline Restore and snapshot handling.


if __name__ == '__main__':
    main()
