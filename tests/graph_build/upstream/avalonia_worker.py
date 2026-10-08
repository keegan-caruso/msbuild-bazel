"""Qualify a prepared SimpleTheme public graph: worker replay and fresh controls.

The disposable workspace must contain graph.generated.json, an app_graph named
'graph' with linux_stable_paths/linux_worker enabled, and its pinned package feed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qualify import DOTNET, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--seed-evidence', type=Path, help='Compare a fresh consumer with a preserved producer output manifest')
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--only', nargs='+', choices=['xaml', 'body', 'api', 'tool'])
    args = parser.parse_args()
    root = args.workspace.resolve()
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    contract = json.loads((root / 'graph.generated.json').read_text())
    entry = Path(contract['Entry'])
    assert entry.name == 'Avalonia.Themes.Simple.csproj'
    upstream = entry.parents[2]
    declarations = [variant for project in contract['Projects'].values()
                    for variant in project.get('Configurations') or [project]]
    outputs = {directory for project in declarations for directory in project['OutputDirectories']}
    count = sum(bool(project['OutputDirectories']) for project in declarations)
    assert count == 23, count
    prefix = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    env = dict(os.environ, USE_BAZEL_VERSION='9.3.0')
    endpoint = env.pop('RULES_MSBUILD_PROJECT_CACHE_URL')
    env.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    probe = results / 'inspect'
    probe.mkdir(exist_ok=True)
    (probe / 'Program.cs').write_text((ROOT / 'tests/fixtures/Inspect.cs.txt').read_text())
    (probe / 'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
        '<OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    with (results / 'inspect-build.log').open('w') as log:
        subprocess.run([DOTNET, 'build', probe / 'Inspect.csproj', '-c', 'Release', '-p:UseSharedCompilation=false'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    program = probe / 'bin/Release/net10.0/Inspect.dll'
    rows = []

    def invoke(label, *arguments):
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(prefix + list(arguments), cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    def capture(label, expected_count):
        artifact = root / 'bazel-bin/graph.graph'
        report = json.loads((artifact / 'report.json').read_text())
        workspace = artifact / 'workspace'
        hashes = {str(path.relative_to(workspace)): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': path.stat().st_mode & 0o777}
                  for directory in outputs for path in (workspace / directory).rglob('*')
                  if path.is_file() and not path.name.endswith('.AssemblyReference.cache')}
        runtime = json.loads(subprocess.check_output([DOTNET, program, 'run', workspace / entry.parent / 'bin/Release/net8.0'], env=env, text=True))
        assert runtime['count'] == expected_count and runtime['resources'] == ['!AvaloniaResources'], runtime
        (results / (label + '.json')).write_text(json.dumps({'report': report, 'runtime': runtime, 'outputs': hashes}, indent=2) + '\n')
        rows.append({'case': label, 'hits': report['hits'], 'misses': report['misses'], 'runtime': runtime})
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(rows[-1]), flush=True)
        return report, hashes

    def build(label, expected_count, worker=True):
        arguments = ['build', '//:graph', '--jobs=4', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
                     '--strategy=MSBuildGraph=' + ('worker' if worker else 'linux-sandbox'), '--spawn_strategy=linux-sandbox']
        if worker:
            arguments.append('--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint)
        invoke(label, *arguments)
        return capture(label, expected_count)

    original = {}
    try:
        if args.seed_evidence:
            seed = json.loads(args.seed_evidence.read_text())['outputs']
        else:
            _, seed = capture('seed', 1)
            invoke('stop-seed-worker', 'shutdown')
        invoke('clean-seed', 'clean')
        replay, recovered = build('fresh-replay', 1)
        assert replay['hits'] == count and recovered == seed, 'Fresh remote replay differs from seed'
        edits = json.loads(Path(__file__).with_name('avalonia_edits.json').read_text())
        edits.insert(0, {'name': 'xaml', 'path': 'src/Avalonia.Themes.Simple/SimpleTheme.xaml', 'before': '</Styles>',
                         'after': '  <Style Selector="Button"><Setter Property="Opacity" Value="0.73" /></Style>\n</Styles>'})
        for edit in edits:
            if args.only and edit['name'] not in args.only:
                continue
            path = root / upstream / edit['path']
            original[path] = path.read_bytes()
            before, after = edit['before'].encode(), edit['after'].encode()
            assert original[path].count(before) == 1
            try:
                path.write_bytes(original[path].replace(before, after))
                expected_count = 2 if edit['name'] == 'xaml' else 1
                report, cached = build(edit['name'], expected_count)
                assert report['misses'] > 0, report
                if edit['name'] == 'xaml':
                    assert report['hits'] == count - 1 and report['misses'] == 1, report
                invoke(edit['name'] + '-clean-control', 'clean')
                control, fresh = build(edit['name'] + '-control', expected_count, worker=False)
                assert control['hits'] == 0 and control['misses'] == count, control
                differences = {'missing': sorted(cached.keys() - fresh.keys()), 'extra': sorted(fresh.keys() - cached.keys()),
                               'changed': sorted(path for path in cached.keys() & fresh.keys() if cached[path] != fresh[path])}
                (results / (edit['name'] + '-parity.json')).write_text(json.dumps(differences, indent=2) + '\n')
                assert not any(differences.values()), differences
            finally:
                path.write_bytes(original[path])
        print('PASS: SimpleTheme remote replay, selected edits (' + ', '.join(args.only or ['xaml', 'body', 'api', 'tool']) + '), runtime execution and fresh native output parity')
    finally:
        for path, content in original.items():
            path.write_bytes(content)
        subprocess.run(prefix + ['shutdown'], cwd=root, env=env, capture_output=True)


if __name__ == '__main__':
    main()
