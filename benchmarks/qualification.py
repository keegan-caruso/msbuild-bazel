"""Compare cold private compiler qualification on the same synthetic graph.

Build both ProjectSync runners first. Each invocation owns a new private build;
the authored workspace and SDK stay fixed. Reports remain outside Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--baseline-runner', type=Path, required=True)
    parser.add_argument('--candidate-runner', type=Path, required=True)
    parser.add_argument('--width', type=int, default=4)
    parser.add_argument('--depth', type=int, default=4)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    assert min(args.width, args.depth, args.samples) > 0
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    version = json.loads((Path(__file__).resolve().parents[1] / 'global.json').read_text())['sdk']['version']
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = output / 'workspace'
    root.mkdir()
    count = args.width * args.depth
    for number in range(count + 1):
        name = 'P' + str(number)
        folder = root / name
        folder.mkdir()
        dependencies = list(range(count - args.width, count)) if number == count else [number - args.width] if number >= args.width else []
        references = ''.join('<ProjectReference Include="../P{0}/P{0}.csproj" />'.format(value) for value in dependencies)
        (folder / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net' + version.split('.')[0] + '.0</TargetFramework></PropertyGroup><ItemGroup>' + references + '</ItemGroup></Project>')
        value = '+'.join('P' + str(dependency) + '.Value()' for dependency in dependencies) or '1'
        methods = ''.join('public static int Method{0}(int value) => value + {0};\n'.format(method) for method in range(256))
        (folder / 'Code.cs').write_text('public static class ' + name + ' { public static int Value() => ' + value + ';\n' + methods + '}\n')
    rows, expected = [], None
    environment = dict(os.environ, DOTNET_ROOT=str(sdk), RULES_MSBUILD_SYNC_PROFILE='1',
        DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1')
    for sample in range(args.samples):
        order = ['baseline', 'candidate'] if sample % 2 == 0 else ['candidate', 'baseline']
        for mode in order:
            runner = getattr(args, mode + '_runner').resolve()
            command = [str(sdk / 'dotnet'), str(runner), str(root), str(sdk / 'sdk' / version),
                'P{0}/P{0}.csproj'.format(count), '--package-build', '--resolve-references']
            start = time.monotonic()
            log = output / (mode + '-' + str(sample) + '.log')
            with log.open('w') as stream:
                subprocess.run(command, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=True)
            seconds = time.monotonic() - start
            hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in ['graph.generated.json', 'graph.generated.bzl']}
            assert expected is None or hashes == expected, 'Serial/parallel declarations differ'
            expected = hashes
            assert not any(root.glob('P*/bin')) and not any(root.glob('P*/obj')), 'Qualification touched authored outputs'
            phases = {value['phase']: value['seconds'] for line in log.read_text().splitlines()
                if line.startswith('PROJECT_SYNC_PROFILE ') for value in [json.loads(line.split(' ', 1)[1])]}
            row = dict(mode=mode, sample=sample, seconds=seconds, phases=phases, outputs=hashes)
            rows.append(row)
            (output / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
            print(json.dumps(row), flush=True)
    print(json.dumps({mode: {phase: statistics.median(row['seconds'] if phase == 'command' else row['phases'][phase]
        for row in rows if row['mode'] == mode) for phase in ['command', 'private-build']}
        for mode in ['baseline', 'candidate']}), flush=True)


if __name__ == '__main__':
    main()
