#!/usr/bin/env python3
"""Execute pinned Dapper.AOT interception, location mutations and cache recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import re
import zipfile

from bazel_session import BazelSession
from prepare_graph import prepare
from probe_bazel import json_stream
from probe_generator_roles import Probe, ROOT, DOTNET_ROOT, BAZEL, inventory, remove_tree
from probe_graph_cache import cache_environment

REVISION = 'bebc9e49bcb8c5e24474e678f3e6716373db7f09'
VERSION = '1.0.85-gbebc9e49bc'
FIXTURE = ROOT / 'tests/fixtures/dapper-interceptors'


class InterceptorProbe(Probe):
    def __init__(self, output, packages):
        super().__init__(output)
        self.packages = Path(packages).resolve()
        archive = self.packages / ('dapper.aot/' + VERSION + '/dapper.aot.' + VERSION + '.nupkg')
        with zipfile.ZipFile(archive) as package:
            nuspec = package.read('Dapper.AOT.nuspec').decode()
            assert 'commit="' + REVISION + '"' in nuspec
        self.report.update(scope='R05-Dapper-interceptors', revision=REVISION,
            packageVersion=VERSION, acquiredArchiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            locationEncoding='InterceptsLocationAttribute(path, line, column)',
            feature='InterceptorsPreviewNamespaces=Dapper.AOT')

    def copy(self, destination, case):
        shutil.copytree(FIXTURE, destination)
        shutil.copytree(self.packages, destination / '.nuget/packages')
        path = destination / 'Program.cs'
        source = path.read_text()
        if case == 'rename':
            path.rename(destination / 'Renamed.cs')
        elif case == 'lines':
            path.write_text('\n\n\n' + source)
        elif case == 'call':
            path.write_text(source.replace('select 42', 'select 43').replace('result != 42', 'result != 43'))
        elif case == 'removed':
            path.write_text(source.replace('var result = connection.ExecuteScalar<int>("select 42");', 'var result = 0;').replace('intercepted:', 'removed:').replace('result != 42', 'result != 0'))
        elif case == 'disabled':
            path.write_text(source.replace('[module: DapperAot]', '[module: DapperAot(false)]'))
        elif case == 'featureDisabled':
            project = destination / 'App.csproj'
            project.write_text(re.sub(r'<InterceptorsPreviewNamespaces>.*?</InterceptorsPreviewNamespaces>', '', project.read_text()))
        elif case == 'language':
            project = destination / 'App.csproj'
            project.write_text(project.read_text().replace('<Nullable>enable</Nullable>', '<Nullable>enable</Nullable><LangVersion>11</LangVersion>'))
        elif case == 'consumer':
            path.write_text(source + '\n// fresh relocated consumer compilation\n')

    def restore(self, source, name):
        self.run(name + '-restore', [DOTNET_ROOT / 'dotnet', 'restore', 'App.csproj', '--packages', source / '.nuget/packages'], source)

    def generate(self, case):
        remove_tree(self.source)
        self.copy(self.source, case)
        self.restore(self.source, case)
        request = self.output / (case + '-request.json')
        manifest = self.output / (case + '-manifest.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(self.source), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.400', packageRoot=str(self.source / '.nuget/packages'),
            entryPoints=[dict(project='App.csproj', globalProperties=dict(Configuration='Release'))], output=str(manifest))))
        self.run(case + '-export', [DOTNET_ROOT / 'dotnet', ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], self.source)
        remove_tree(self.generated)
        self.graph = prepare(self.source, manifest, self.generated, environment=cache_environment(self.output, self.source))
        assert len(self.graph['nodes']) == 1
        self.node = self.graph['nodes'][0]
        remove_tree(self.source)

    def observe(self, case, directory, label=None):
        result = self.run((label or case) + '-runtime', [DOTNET_ROOT / 'dotnet', directory / 'App.dll'], self.output, success=case != 'disabled')
        if case == 'disabled':
            assert result.returncode and 'Dapper AOT interception did not execute' in result.stdout and 'Dapper.SqlMapper' in result.stdout
            return dict(fallbackRejected=True)
        expected = 'removed:0' if case == 'removed' else 'intercepted:43' if case == 'call' else 'intercepted:42'
        assert result.stdout.strip() == expected, result.stdout
        runtime = sorted(p.name for p in directory.glob('*.dll'))
        assert runtime == ['App.dll', 'Dapper.AOT.dll', 'Dapper.dll'], runtime
        return dict(output=expected, runtimeFiles=runtime)

    def ordinary(self, case):
        source = self.output / ('ordinary-' + case)
        self.copy(source, case)
        self.restore(source, 'ordinary-' + case)
        fail = case in ('featureDisabled', 'language')
        result = self.run('ordinary-' + case + '-build', [DOTNET_ROOT / 'dotnet', 'build', 'App.csproj', '-c', 'Release', '--no-restore', '-v:normal'], source, success=not fail)
        if fail:
            assert result.returncode and 'error CS' in result.stdout
            observed = dict(diagnostics=sorted(set(re.findall(r'error (CS[0-9]+)', result.stdout))))
        else:
            observed = self.observe(case, source / 'bin/Release/net10.0', 'ordinary-' + case)
            generated = list((source / 'obj').rglob('App.generated.cs'))
            if case in ('disabled', 'removed'):
                assert all('[global::System.Runtime.CompilerServices.InterceptsLocationAttribute(' not in p.read_text() for p in generated)
            if case not in ('disabled', 'removed'):
                assert len(generated) == 1 and 'InterceptsLocationAttribute(' in generated[0].read_text()
                (self.output / (case + '-generated.cs')).write_text(generated[0].read_text())
        remove_tree(source)
        return observed

    def build(self, case, baseline):
        execution = self.output / (case + '-execution.json')
        fail = case in ('featureDisabled', 'language')
        result = self.run(case + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.base), '--output_user_root=' + str(self.output / 'bazel-user'),
            'build', '//:node_' + self.node['id'], '--disk_cache=' + str(self.output / 'disk-cache'),
            '--spawn_strategy=' + self.strategy, '--strategy=MsbuildProject=' + self.strategy, '--jobs=2',
            '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all',
            '--execution_log_json_file=' + str(execution)], self.generated, success=not fail)
        actions = [dict(cacheHit=r.get('cacheHit', False), runner=r.get('runner')) for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
        expected = 0 if case in ('unchanged', 'relocated') else 1
        assert sum(not a['cacheHit'] for a in actions) == expected, actions
        assert all(a['cacheHit'] or a['runner'] == self.strategy for a in actions)
        bundle = self.generated / ('bazel-bin/node_' + self.node['id'] + '.bundle')
        if fail:
            assert result.returncode and all('error ' + code in result.stdout for code in baseline['diagnostics'])
            assert not (bundle / 'bundle.json').exists()
            observed = baseline
        else:
            observed = self.observe(case, bundle / 'artifacts/bin/Release/net10.0')
            assert observed == baseline
            diagnostic = self.generated / ('bazel-bin/node_' + self.node['id'] + '.diagnostics/action.json')
            assert json.loads(diagnostic.read_text())['compiledProjects'] == ['App']
        if case == 'relocated':
            assert actions == [dict(cacheHit=True, runner='disk cache hit')]
        item = dict(actions=actions, observable=observed, preparationWorkspaceAbsent=not self.source.exists(),
            bundle=inventory(bundle) if not fail else None)
        self.report['cases'][case] = item
        self.save()
        return item

    def execute(self):
        stage = 'bootstrap'
        try:
            self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
            with BazelSession(self.output) as self.session:
                for case in ('cold', 'unchanged', 'rename', 'lines', 'call', 'removed', 'disabled', 'featureDisabled', 'language'):
                    stage = case
                    ordinary = self.ordinary(case)
                    self.generate(case)
                    item = self.build(case, ordinary)
                    if case == 'cold': cold, baseline = item, ordinary
            remove_tree(self.generated)
            remove_tree(self.base)
            self.generated = self.output / 'recovered-generated'
            self.source = self.output / 'recovered-source'
            self.base = self.output / 'recovered-base'
            with BazelSession(self.output) as self.session:
                stage = 'relocated'
                self.generate(stage)
                recovered = self.build(stage, baseline)
                assert recovered['bundle'] == cold['bundle']
                stage = 'consumer'
                ordinary = self.ordinary(stage)
                self.generate(stage)
                self.build(stage, ordinary)
            self.report['accepted'] = True
        except BaseException as error:
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    InterceptorProbe(args.output, args.packages).execute()
