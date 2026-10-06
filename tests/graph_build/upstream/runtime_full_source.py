"""Compare a qualified graph with raw MSBuild from the complete pinned source.

This correctness control uses the graph's configured entry points, declared
packages, SDK, four nodes and stable paths. Its elapsed time is not a scorecard.
"""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from runtime_benchmark import expand_raw_packages
from runtime_prepare import COMMIT, SOURCE_SHA256

from runtime_root_properties import root_properties

ROOT = Path(__file__).resolve().parents[3]


def capture_compiled_products(workspace, contract):
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    directories = {p for v in variants for p in v['OutputDirectories']}
    files = {p for v in variants for p in v.get('OutputFiles', [])}
    paths = {workspace / path for path in files} | {p for directory in directories for p in (workspace / directory).rglob('*')}
    return {str(p.relative_to(workspace)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
            for p in paths if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']
            and not (str(p.relative_to(workspace)).startswith('artifacts/obj/') and '/PreTrim/' in str(p.relative_to(workspace)))}


def replay_omissions(contract):
    """Explicit optional files only; the runner also checks SDK target metadata."""
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    required = {p for v in variants for p in v.get('OutputFiles', [])}
    required |= {p for v in variants for pair in v.get('DependencyCopies', {}).items() for p in pair}
    required |= {p for v in variants for p in v.get('CompilerReferences', {}).values()}
    required |= {v['CompilerReference'] for v in variants if v.get('CompilerReference')}
    paths = set()
    for variant in variants:
        for path in variant.get('ReplayOmissions', []):
            parts = path.split('/')
            assert not path.startswith('/') and not any(p in ['', '.', '..'] for p in parts) and '\\' not in path, path
            assert path.endswith(('.dll', '.pdb')) and parts[-2] not in ['ref', 'refint'], path
            assert path not in required and any(path.startswith(d.rstrip('/') + '/') for d in variant['OutputDirectories']), path
            paths.add(path)
    return paths


def normalize_reference_bindings(contract, previous, references):
    """Permit the reviewed cache bindings while requiring unchanged raw build semantics."""
    assert references['sdkVersion'] == contract['SdkVersion']
    selected = 0
    for project, configurations in references['projects'].items():
        for configuration in configurations:
            variants = contract['Projects'][project].get('Configurations') or [contract['Projects'][project]]
            old_variants = previous['Projects'][project].get('Configurations') or [previous['Projects'][project]]
            variant = next(v for v in variants if v.get('Properties', {}) == configuration['properties'])
            old = next(v for v in old_variants if v.get('Properties', {}) == configuration['properties'])
            assert variant['OutputDirectories'], ('Noncompilation binding', project)
            for field, name in [('ReferenceBoundary', 'referenceBoundary'), ('CompilerReference', 'compilerReference'),
                                ('CompilerReferences', 'compilerReferences'), ('ImplementationDependencies', 'implementationDependencies')]:
                assert variant[field] == configuration['bindings'][name], ('Unexpected cache binding', project, field)
                variant[field] = old.get(field)
            assert configuration['bindings']['dependencyCopies'].items() <= variant['DependencyCopies'].items(), ('Missing selected copy', project)
            variant['DependencyCopies'] = old.get('DependencyCopies', {})
            selected += 1
    assert selected == references['compiledNodes'] == 481


def validate_raw_contract(contract, raw_results, allow_replay_omissions=False, evaluation_reuse_inputs=None,
                          reference_bindings=None):
    """Allow inventoried outputs and explicitly reviewed replay/evaluation controls."""
    previous = json.loads((raw_results / 'raw-workspace/graph.generated.json').read_text())
    inventory = json.loads((raw_results / 'binplace.json').read_text())
    candidate = copy.deepcopy(contract)
    if reference_bindings:
        normalize_reference_bindings(candidate, previous, reference_bindings)
    if evaluation_reuse_inputs is not None:
        assert contract['Version'] == 9 and previous['Version'] <= 9
        assert previous.get('EvaluationReuseInputs') in [None, sorted(evaluation_reuse_inputs)], 'Unexpected raw evaluation exemption'
        assert contract['EvaluationReuseInputs'] == sorted(evaluation_reuse_inputs), 'Unexpected evaluation exemption'
    def semantics(value):
        value = copy.deepcopy(value)
        if evaluation_reuse_inputs is not None:
            value.pop('EvaluationReuseInputs', None)
            value['Version'] = previous['Version']
        for project in value['Projects'].values():
            for variant in [project] + project.get('Configurations', []):
                variant.pop('OutputFiles', None)
                if allow_replay_omissions:
                    variant.pop('ReplayOmissions', None)
        return value
    assert semantics(previous) == semantics(candidate), 'Raw semantic contract differs'
    if allow_replay_omissions:
        assert not replay_omissions(previous), 'Raw control must retain the complete intermediates'
        assert replay_omissions(contract), 'No explicit candidate omissions'
    for path, project in contract['Projects'].items():
        old = previous['Projects'][path]
        for variant, original in zip([project] + project.get('Configurations', []),
                                     [old] + old.get('Configurations', []), strict=True):
            before, after = set(original.get('OutputFiles', [])), set(variant.get('OutputFiles', []))
            assert before <= after, ('Removed output ownership', path)
            if not after - before:
                continue
            frameworks = inventory.get(path, {})
            framework = variant.get('Properties', {}).get('TargetFramework')
            if framework is None:
                assert len(frameworks) == 1, ('Ambiguous evaluated ownership framework', path)
                framework = next(iter(frameworks))
            reviewed = set(frameworks.get(framework, []))
            assert after - before <= reviewed, ('Unreviewed output ownership change', path, framework)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_archive', type=Path)
    parser.add_argument('workspace', type=Path, help='completed runtime_qualify.py workspace')
    parser.add_argument('results', type=Path, help='new disposable directory')
    parser.add_argument('--replay-omissions', action='store_true', help='compare all required products and require explicit optional intermediates to be absent')
    parser.add_argument('--inventory-only', action='store_true', help='raw Build and target-derived binplace inventory before graph qualification')
    args = parser.parse_args()
    assert not args.replay_omissions or not args.inventory_only
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert hashlib.sha256(args.source_archive.read_bytes()).hexdigest() == SOURCE_SHA256
    root, results = args.workspace.resolve(), args.results.resolve()
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    expected = None if args.inventory_only else (root / 'bazel-bin/graph.graph/workspace').resolve(strict=True)
    results.mkdir(parents=True, exist_ok=False)
    with tarfile.open(args.source_archive) as archive:
        archive.extractall(results, filter='data')
    raw = results / 'raw-workspace'
    (results / ('runtime-' + COMMIT)).rename(raw)
    shutil.copytree(root / '.package-source', raw / '.package-source')
    contract = json.loads((root / 'graph.generated.json').read_text())
    (raw / 'graph.generated.json').write_text(json.dumps(contract) + '\n')
    expansion_seconds = expand_raw_packages(raw)
    (raw / 'NuGet.Config').write_text('<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    env = dict(os.environ, DOTNET_ROOT=str(sdk), DOTNET_HOST_PATH=str(sdk / 'dotnet'), MSBUILDDISABLENODEREUSE='1')
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        env.pop(key, None)

    def run(command, label, cwd):
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    driver = results / 'driver'
    driver.mkdir()
    directory = Path(__file__).resolve().parent
    shutil.copyfile(directory / 'RuntimeRawGraph.cs.txt', driver / 'Program.cs')
    shutil.copyfile(directory / 'RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
    run([str(sdk / 'dotnet'), 'build', str(driver / 'Raw.csproj'), '-c', 'Release', '-p:NuGetAudit=false', '-p:UseSharedCompilation=false'], 'driver-build', ROOT)
    shutil.copytree(driver / 'bin/Release/net10.0', raw / '.qualification')
    scratch = results / 'scratch'
    scratch.mkdir()
    stable = '/__rules_msbuild_graph/output/workspace'
    stable_sdk = '/__rules_msbuild_graph/sdk'
    host = ['bash', str(directory / 'runtime_raw.sh'), str(sdk), str(raw), str(scratch)]
    for index, entry in enumerate(contract.get('Entries') or [contract['Entry']]):
        properties = [f'-p:{k}={v}' for k, v in root_properties(contract, entry).items() if k.lower() != 'targetframework']
        run(host + ['restore', stable + '/' + entry, '--configfile', stable + '/NuGet.Config', '--source', stable + '/.package-source', '--packages', stable + '/.nuget', '-p:NuGetAudit=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion'], *properties], 'restore-' + str(index), raw)
    run(host + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'build'], 'raw-build', raw)
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    if args.inventory_only:
        run(host + [stable + '/.qualification/Raw.dll', stable, stable + '/graph.generated.json', 'binplace', stable + '/.qualification/binplace.json'], 'binplace', raw)
        shutil.copyfile(raw / '.qualification/binplace.json', results / 'binplace.json')
        inventory = json.loads((results / 'binplace.json').read_text())
        print(json.dumps(dict(commit=COMMIT, sourceSha256=SOURCE_SHA256, configuredNodes=len(variants),
                              projects=len(contract['Projects']), producerConfigurations=sum(len(v) for v in inventory.values()),
                              sharedFiles=sum(len(paths) for v in inventory.values() for paths in v.values()),
                              scope='raw Build and SDK BinPlace ownership; not graph parity or scored timing')), flush=True)
        return
    graph_outputs, raw_outputs = capture_compiled_products(expected, contract), capture_compiled_products(raw, contract)
    omitted = replay_omissions(contract) if args.replay_omissions else set()
    if omitted:
        assert not omitted & graph_outputs.keys(), 'Optional intermediates were published'
        assert omitted <= raw_outputs.keys(), 'Candidate must exist in the complete raw control'
        raw_outputs = {p: v for p, v in raw_outputs.items() if p not in omitted}
    differences = {p: {'graph': graph_outputs.get(p), 'raw': raw_outputs.get(p)}
                   for p in sorted(graph_outputs.keys() | raw_outputs.keys())
                   if graph_outputs.get(p, {}).get('sha256') != raw_outputs.get(p, {}).get('sha256')}
    report = dict(commit=COMMIT, sourceSha256=SOURCE_SHA256, entries=contract.get('Entries') or [contract['Entry']],
                  configuredNodes=len(variants), compilationNodes=sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants),
                  comparedDllPdbResourceFiles=len(graph_outputs), omittedIntermediateFiles=len(omitted), differences=differences,
                  observedFileModes={name: dict(Counter(oct(v['mode']) for v in outputs.values())) for name, outputs in [('graph', graph_outputs), ('raw', raw_outputs)]},
                  packageExpansionSeconds=expansion_seconds, scope='full upstream source; compiled-product byte parity, not scored timing')
    (results / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    assert graph_outputs and not differences, 'Full-source byte parity failed; inspect summary.json'
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
