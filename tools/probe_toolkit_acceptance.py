#!/usr/bin/env python3
"""Pinned CommunityToolkit configured graph and generated-behavior acceptance."""
import argparse
import json
from pathlib import Path
import re
import shutil

from bazel_session import BazelSession
from prepare_graph import prepare
from probe_bazel import json_stream
from probe_generator_roles import Probe, ROOT, DOTNET_ROOT, BAZEL, inventory, remove_tree
from probe_graph_cache import cache_environment

REVISION = 'b135626dd54d33b8f05f2ff31591592c004aa848'
TEST = 'CommunityToolkit.Mvvm.Roslyn4001.UnitTests'
PROJECT = 'tests/' + TEST + '/' + TEST + '.csproj'
FILTER = 'FullyQualifiedName~Test_ObservablePropertyAttribute|FullyQualifiedName~Test_RelayCommandAttribute'


class ToolkitProbe(Probe):
    def __init__(self, output, upstream):
        super().__init__(output)
        self.upstream = Path(upstream).resolve()
        self.report.update(scope='R05-CommunityToolkit-selected-net10', revision=REVISION)

    def copy(self, destination, case):
        self.run(case + '-clone', ['git', 'clone', '--local', '--no-hardlinks', self.upstream, destination], self.output)
        self.run(case + '-checkout', ['git', 'checkout', '--detach', REVISION], destination)
        self.run(case + '-origin', ['git', 'remote', 'set-url', 'origin', 'https://github.com/CommunityToolkit/dotnet'], destination)
        (destination / '.git/index').unlink()
        self.run(case + '-index', ['git', 'read-tree', 'HEAD'], destination)
        path = destination / 'Directory.Build.targets'
        path.write_text(path.read_text().replace('</Project>', '<ItemGroup><BazelExtraInput Include="$(MSBuildThisFileDirectory)version.json" /></ItemGroup></Project>'))
        shutil.copytree(self.upstream / '.nuget/packages', destination / '.nuget/packages')
        if case == 'generator':
            path = destination / 'src/CommunityToolkit.Mvvm.SourceGenerators/ComponentModel/ObservablePropertyGenerator.Execute.cs'
            path.write_text(path.read_text() + '\n// acceptance generator implementation input\n')
        elif case == 'conditionalPackage':
            path = destination / 'src/CommunityToolkit.Mvvm/CommunityToolkit.Mvvm.csproj'
            path.write_text(path.read_text().replace('Include="Microsoft.Bcl.AsyncInterfaces" Version="10.0.1"', 'Include="Microsoft.Bcl.AsyncInterfaces" Version="10.0.11"'))
        elif case == 'supportingPackage':
            path = destination / 'src/Directory.Build.props'
            path.write_text(path.read_text().replace('Version="1.15.0"', 'Version="1.16.0"'))
        elif case == 'consumer':
            path = destination / 'tests/CommunityToolkit.Mvvm.UnitTests/Test_ObservablePropertyAttribute.cs'
            path.write_text(path.read_text() + '\n// acceptance consumer input\n')

    def restore(self, source, name):
        self.run(name + '-restore', [DOTNET_ROOT / 'dotnet', 'restore', PROJECT, '-p:EnableWindowsTargeting=true'], source)

    def export(self, source, name):
        request, manifest = (self.output / (name + suffix) for suffix in ('-request.json', '-manifest.json'))
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.400', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties=dict(Configuration='Release', TargetFramework='net10.0'))], output=str(manifest))))
        self.run(name + '-export', [DOTNET_ROOT / 'dotnet', ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
        return manifest

    def generate(self, case):
        remove_tree(self.source)
        self.copy(self.source, case)
        self.restore(self.source, case)
        manifest = self.export(self.source, case)
        remove_tree(self.generated)
        self.graph = prepare(self.source, manifest, self.generated, environment=cache_environment(self.output, self.source))
        self.nodes = {n['id']: n for n in self.graph['nodes']}
        assert len(self.nodes) == 11
        self.entry = next(n for n in self.nodes.values() if n['project'] == 'workspace/' + PROJECT)
        assert sorted(n['targetFramework'] for n in self.nodes.values() if n['project'].endswith('/CommunityToolkit.Mvvm.csproj')) == ['net8.0', 'netstandard2.0']
        remove_tree(self.source)

    def observe(self, name, directory):
        result = self.run(name + '-test', [DOTNET_ROOT / 'dotnet', 'vstest', directory / (TEST + '.dll'), '--TestCaseFilter:' + FILTER], self.output)
        # VSTest output is the actual upstream behavioral oracle, not generated-file existence.
        assert re.search(r'(?:Passed:\s*|Passed!\s+-.*?Passed:\s*)69\b', result.stdout), result.stdout
        assert not re.search(r'Failed:\s*[1-9]', result.stdout), result.stdout
        runtime = sorted(p.name for p in directory.glob('*.dll'))
        assert not any('SourceGenerators' in p or 'CodeFixers' in p for p in runtime), runtime
        return dict(passed=69, runtimeFiles=runtime)

    def ordinary(self, case):
        source = self.output / ('ordinary-' + case)
        self.copy(source, case)
        self.restore(source, 'ordinary-' + case)
        self.run('ordinary-' + case + '-build', [DOTNET_ROOT / 'dotnet', 'build', PROJECT, '-c', 'Release', '-f', 'net10.0', '--no-restore'], source)
        result = self.observe('ordinary-' + case, source / ('tests/' + TEST + '/bin/Release/net10.0'))
        remove_tree(source)
        return result

    def build(self, case, baseline):
        execution = self.output / (case + '-execution.json')
        self.run(case + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.base), '--output_user_root=' + str(self.output / 'bazel-user'),
            'build', '//:node_' + self.entry['id'], '--disk_cache=' + str(self.output / 'disk-cache'),
            '--spawn_strategy=' + self.strategy, '--strategy=MsbuildProject=' + self.strategy, '--jobs=2',
            '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all',
            '--execution_log_json_file=' + str(execution)], self.generated)
        actions = []
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject': continue
            identity = record['targetLabel'].split(':node_')[-1]
            node = self.nodes[identity]
            name = Path(node['project']).stem
            action = dict(id=identity, project=name, framework=node['targetFramework'], cacheHit=record.get('cacheHit', False), runner=record.get('runner'))
            if not action['cacheHit']:
                assert action['runner'] == self.strategy
                diagnostic = self.generated / ('bazel-bin/node_' + identity + '.diagnostics/action.json')
                assert json.loads(diagnostic.read_text())['compiledProjects'] == [name]
            actions.append(action)
        executed = {a['id'] for a in actions if not a['cacheHit']}
        expected = set(self.nodes) if case == 'cold' else {self.entry['id']} if case == 'consumer' else set()
        if case == 'conditionalPackage':
            expected = {i for i,n in self.nodes.items() if Path(n['project']).stem in ('CommunityToolkit.Mvvm', 'CommunityToolkit.Mvvm.ExternalAssembly.Roslyn4001', TEST)}
        elif case == 'supportingPackage':
            expected = set(self.nodes)
        if case == 'generator':
            # Infer the exact affected work set from the exported source ownership and DAG.
            changed = 'workspace/src/CommunityToolkit.Mvvm.SourceGenerators/ComponentModel/ObservablePropertyGenerator.Execute.cs'
            expected = {i for i,n in self.nodes.items() if any(x['path'] == changed and x['kind'] == 'source' for x in n['inputs'])}
            while True:
                expanded = expected | {i for i,n in self.nodes.items() if set(n['dependencies']) & expected}
                if expanded == expected: break
                expected = expanded
        assert executed == expected, actions
        if case == 'relocated':
            assert len(actions) == 11 and all(a['cacheHit'] and a['runner'] == 'disk cache hit' for a in actions)
        bundles = {i: self.generated / ('bazel-bin/node_' + i + '.bundle') for i in self.nodes}
        directory = bundles[self.entry['id']] / ('artifacts/tests/' + TEST + '/bin/Release/net10.0')
        observed = self.observe(case, directory)
        assert observed == baseline
        item = dict(actions=actions, observable=observed, preparationWorkspaceAbsent=not self.source.exists(),
                    bundles={i: inventory(p) for i,p in bundles.items()})
        self.report['cases'][case] = item
        self.save()
        return item

    def execute(self, cold_only):
        stage = 'bootstrap'
        try:
            self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
            baseline = self.ordinary('cold')
            with BazelSession(self.output) as self.session:
                for case in ('cold',) if cold_only else ('cold', 'unchanged', 'generator', 'conditionalPackage', 'supportingPackage'):
                    stage = case
                    ordinary = baseline if case in ('cold', 'unchanged') else self.ordinary(case)
                    self.generate(case)
                    item = self.build(case, ordinary)
                    if case == 'cold': cold = item
            if not cold_only:
                stage = 'relocated'
                remove_tree(self.generated)
                remove_tree(self.base)
                self.generated = self.output / 'recovered-generated'
                self.source = self.output / 'recovered-source'
                self.base = self.output / 'recovered-base'
                with BazelSession(self.output) as self.session:
                    self.generate(stage)
                    recovered = self.build(stage, baseline)
                    assert recovered['bundles'] == cold['bundles']
                    stage = 'consumer'
                    ordinary = self.ordinary(stage)
                    self.generate(stage)
                    self.build(stage, ordinary)
            self.report['coldAccepted' if cold_only else 'accepted'] = True
        except BaseException as error:
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cold-only', action='store_true')
    args = parser.parse_args()
    ToolkitProbe(args.output, args.source).execute(args.cold_only)
