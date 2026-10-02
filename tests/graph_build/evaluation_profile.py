"""Run production evaluation diagnostics in fresh processes, without compiling the graph."""
import argparse
import json
import os
from pathlib import Path
import shutil

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def input_view(destination, workspace, prepared, contract):
    """Copy declarations and Restore products; exclude retained compiler outputs."""
    destination.mkdir()
    paths = set(contract['SharedInputs']) | set(contract['Projects'])
    paths.update(contract.get('DefinitionDigests', {}))
    paths.update(contract.get('Restore', {}).get('Inputs', []))
    for project in contract['Projects'].values():
        for selected in [project, *project.get('Configurations', [])]:
            paths.update(selected['Inputs'])
    if contract.get('ToolProperties'):
        paths.add('.graph-tools/bindings.json')
        for entry in contract['ToolProperties'].values():
            closure = workspace / '/'.join(entry.split('/')[:2])
            paths.update(str(path.relative_to(workspace)) for path in closure.rglob('*') if path.is_file())

    def copy(source, relative):
        path = Path(relative)
        assert not path.is_absolute() and all(part not in ['', '.', '..'] for part in relative.split('/')), relative
        source = source / path
        assert source.resolve(strict=True) == source, source
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == source.read_bytes(), f'Conflicting prepared input: {relative}'
        shutil.copy2(source, target)

    for relative in sorted(paths):
        copy(workspace, relative)
    manifest = json.loads((prepared / 'manifest.json').read_text())
    for relative in manifest['Files']:
        if not relative.startswith('.nuget/'):
            copy(prepared, relative)
    for relative in contract.get('InputDirectories', []):
        path = Path(relative)
        assert not path.is_absolute() and all(part not in ['', '.', '..'] for part in relative.split('/')), relative
        (destination / path).mkdir(parents=True, exist_ok=True)
    (destination / '.nuget').mkdir(exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new disposable results directory')
    parser.add_argument('--workspace', required=True, type=Path, help='retained graph workspace with Restore outputs')
    parser.add_argument('--contract', required=True, type=Path)
    parser.add_argument('--prepared', required=True, type=Path, help='preserved prepared payload with manifest.json')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux'
    base = args.directory.resolve()
    for source in [args.workspace, args.prepared]:
        assert not base.is_relative_to(source.resolve()) and not source.resolve().is_relative_to(base)
    base.mkdir(parents=True, exist_ok=False)
    workspace = base / 'inputs'
    input_view(workspace, args.workspace.resolve(), args.prepared.resolve(), json.loads(args.contract.read_text()))
    driver = base / 'driver'
    driver.mkdir()
    shutil.copyfile(ROOT / 'tests/graph_build/EvaluationProfile.cs.txt', driver / 'Program.cs')
    shutil.copyfile(ROOT / 'tests/graph_build/upstream/RuntimeRawGraph.csproj.txt', driver / 'Probe.csproj')
    build = run(DOTNET, 'build', driver / 'Probe.csproj', '-c', 'Release',
        '-p:UseSharedCompilation=false', '-p:NuGetAudit=false', '-warnaserror')
    (base / 'build.log').write_text(build.stdout + build.stderr)
    for label, profiled in [('off', 'off'), ('phases', 'phases'), ('on', 'evaluation')]:
        result = run('bash', ROOT / 'tests/graph_build/evaluation_profile.sh', SDK, RUNNER.parent,
            workspace, args.prepared.resolve(), args.contract.resolve(), driver / 'bin/Release/net10.0', base, label, profiled)
        (base / (label + '.log')).write_text(result.stdout + result.stderr)
    off, phases, on = [json.loads((base / (label + '.json')).read_text()) for label in ['off', 'phases', 'on']]
    assert off['shapeSha256'] == phases['shapeSha256'] == on['shapeSha256'], 'Profiling changed evaluated graph shape'
    assert off['operations'] is None and off['evaluationProfile'] is None, off
    assert phases['operations'] and phases['evaluationProfile'] is None, phases
    assert on['evaluationProfile']['profiledProjects'] == on['configuredNodes'], on
    summary = dict(scope='one off/phase/detailed evaluation-only control; not build timing or speedup',
        shapeEqual=True, off=off, phases=phases, on=on)
    (base / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({key: on[key] for key in ['configuredNodes', 'physicalProjects', 'compiledNodes', 'initialTargetNodes', 'evaluationSeconds', 'evaluationProfile']}, indent=2))
    print('PASS: profiling off/on evaluated properties, items, imports, references and target selections match')


if __name__ == '__main__':
    main()
