"""Compare a staged upstream graph's snapshot output set with a clean replay."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from qualify import DOTNET, RUNNER, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('contract', type=Path)
    parser.add_argument('cache', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--seed', action='store_true', help='build a clean seed with the same runner and environment first')
    args = parser.parse_args()
    root = args.workspace.resolve()
    contract = json.loads(args.contract.read_text())
    directories = set()
    files = set()
    for project in contract['Projects'].values():
        for declaration in [project] + project.get('Configurations', []):
            for relative in declaration.get('OutputFiles') or []:
                path = root / relative
                assert not path.is_symlink() and path.resolve().is_relative_to(root) and path.resolve() != root
                files.add(path)
            for relative in declaration['OutputDirectories']:
                path = root / relative
                assert not path.is_symlink() and path.resolve().is_relative_to(root) and path.resolve() != root
                directories.add(path)

    # GraphCache deliberately excludes MSBuild's local assembly-resolution cache.
    def outputs():
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in files | {path for directory in directories for path in directory.rglob('*')}
                if path.is_file() and (path in files or not path.name.endswith('.AssemblyReference.cache'))}

    def clear_outputs():
        # Remove only the declared outputs from this disposable workspace.
        for directory in directories:
            shutil.rmtree(directory, ignore_errors=True)
        for path in files:
            path.unlink(missing_ok=True)

    if args.seed:
        clear_outputs()
        run(DOTNET, RUNNER, 'action', root, args.contract.resolve(), args.report.resolve().with_suffix('.seed.json'), args.cache.resolve())
    seed = outputs()
    assert seed, 'Build the staged workspace once before checking replay'
    clear_outputs()
    run(DOTNET, RUNNER, 'action', root, args.contract.resolve(), args.report.resolve(), args.cache.resolve())
    report = json.loads(args.report.read_text())
    assert report['misses'] == 0, report
    replay = outputs()
    assert seed == replay, {'missing': sorted(seed.keys() - replay.keys()),
                            'extra': sorted(replay.keys() - seed.keys()),
                            'changed': [path for path in seed.keys() & replay.keys() if seed[path] != replay[path]][:20]}
    print(f"PASS: {report['hits']} project hits; all {len(seed)} snapshot output files match the seed")


if __name__ == '__main__':
    main()
