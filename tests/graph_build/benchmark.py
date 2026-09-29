"""Paired end-to-end graph-runner and warm raw graph-mode edit timings."""

import argparse
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import time

from qualify import DOTNET, RUNNER, fixture, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--projects', type=int, default=32)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='graph-timing-') as temporary:
        work = Path(temporary).resolve()
        roots = {name: work / name for name in ('cached', 'raw')}
        for root in roots.values():
            root.mkdir()
            contract = fixture(root, args.projects)
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        for i in range(args.projects):
            project = contract['Projects'][f'P{i}/P{i}.csproj']
            project['ReferenceBoundary'] = True
            project['DependencyCopies'] = {
                f'P{i}/bin/Release/net10.0/P{dependency}.{extension}':
                f'P{dependency}/bin/Release/net10.0/P{dependency}.{extension}'
                for dependency in range(i) for extension in ('dll', 'pdb')
            }
        manifest = work / 'contract.json'
        manifest.write_text(json.dumps(contract))
        report = work / 'report.json'
        rows = []

        def build(name):
            root = roots[name]
            if name == 'cached':
                for project in contract['Projects'].values():
                    for path in project['OutputDirectories']:
                        shutil.rmtree(root / path, ignore_errors=True)
                command = [DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache']
            else:
                command = [DOTNET, 'msbuild', root / contract['Entry'], '-graphBuild', '-m:4', '-t:Build',
                           '-p:Configuration=Release', '-p:UseSharedCompilation=false',
                           '-p:DisableTransitiveProjectReferences=true', '-nologo', '-verbosity:quiet']
            start = time.monotonic()
            run(*command)
            row = {'engine': name, 'wallSeconds': time.monotonic() - start}
            if name == 'cached':
                row.update(json.loads(report.read_text()))
            return row

        for name in roots:
            rows.append(dict(build(name), edit='seed'))
        for edit in ('body', 'api'):
            for sample in range(args.samples):
                for name, root in roots.items():
                    extra = f'public static int Added{sample}() => 3;' if edit == 'api' else ''
                    (root / 'P0/Code.cs').write_text(f'public class P0 {{ public static int Value() => {sample + 2}; {extra} }}')
                    rows.append(dict(build(name), edit=edit))
        medians = {edit: {name: statistics.median(r['wallSeconds'] for r in rows if r['edit'] == edit and r['engine'] == name)
                         for name in roots} for edit in ('body', 'api')}
        print(json.dumps({'projects': args.projects, 'samples': args.samples, 'medians': medians, 'runs': rows}, indent=2))


if __name__ == '__main__':
    main()
