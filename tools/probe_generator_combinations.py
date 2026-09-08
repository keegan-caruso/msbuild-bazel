#!/usr/bin/env python3
"""R05a mixed generator delivery, diagnostic-only analyzer and framework probe."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from bazel_session import BazelSession
from probe_generator_roles import Probe, ROOT, DOTNET_ROOT, PROJECT, PROJECTS, edit, mutate, remove_tree


class CombinationProbe(Probe):
    failure_diagnostics = ['ROLE001']
    def __init__(self, output, delivery):
        super().__init__(output)
        self.delivery = delivery
        self.projects = PROJECTS | ({'DiagnosticAnalyzer'} if delivery == 'project' else set())
        self.feed = self.output / 'feed'
        self.report.update(scope='R05a-generator-combinations', analyzerDelivery=delivery)

    def acquire(self):
        """Build versioned local packages outside graph preparation; retain hashes."""
        self.feed.mkdir()
        hashes = {}
        for component in ('PackageGenerator', 'DiagnosticAnalyzer'):
            for version in ('1.0.0', '1.1.0'):
                source = self.output / ('package-source-' + component + '-' + version)
                source.mkdir()
                for name in ('Directory.Build.props', 'global.json', 'NuGet.Config'):
                    shutil.copy2(ROOT / 'tests/fixtures/generator-roles' / name, source / name)
                if component == 'DiagnosticAnalyzer':
                    for path in (ROOT / 'tests/fixtures/diagnostic-analyzer').iterdir():
                        shutil.copy2(path, source / path.name)
                    if version == '1.1.0':
                        edit(source / 'MarkerAnalyzer.cs', '"v1"', '"v2"')
                else:
                    for path in (ROOT / 'tests/fixtures/generator-roles/ClassicGenerator').iterdir():
                        content = path.read_text().replace('ClassicGenerator', component).replace('ClassicGenerated', 'PackageGenerated').replace('GEN001', 'PKG001')
                        (source / path.name.replace('ClassicGenerator', component)).write_text(content)
                    edit(source / 'ClassicValueGenerator.cs', 'out var prefix);',
                        'out var prefix);\n        prefix += "-package-' + version + '";')
                self.run(component + '-' + version, [DOTNET_ROOT / 'dotnet', 'build',
                    component + '.csproj', '-c', 'Release', '--nologo'], source)
                archive = self.feed / (component + '.' + version + '.nupkg')
                with zipfile.ZipFile(archive, 'w') as package:
                    for name, payload in {
                        component + '.nuspec': ('<package><metadata><id>' + component + '</id><version>' + version + '</version><authors>Fixture</authors><description>R05a fixture</description></metadata></package>').encode(),
                        'analyzers/dotnet/cs/' + component + '.dll': (source / 'bin/Release/net10.0' / (component + '.dll')).read_bytes(),
                    }.items():
                        entry = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
                        entry.external_attr = 0o100644 << 16
                        package.writestr(entry, payload)
                hashes[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
                remove_tree(source)
        self.report['acquisitionHashes'] = hashes
        self.save()

    def copy(self, destination):
        super().copy(destination)
        shutil.copytree(self.feed, destination / 'feed')
        edit(destination / 'NuGet.Config', '<clear />', '<clear /><add key="fixture" value="feed" /><add key="nuget.org" value="https://api.nuget.org/v3/index.json" />')
        # Negotiate a compatible dependency TFM rather than imposing net10.0 on it.
        (destination / 'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework></TargetFramework><TargetFrameworks>net10.0;netstandard2.1</TargetFrameworks><LangVersion>latest</LangVersion></PropertyGroup></Project>\n')
        edit(destination / PROJECT, '</Project>', '<ItemGroup><PackageReference Include="PackageGenerator" Version="[1.0.0]" PrivateAssets="all" /></ItemGroup></Project>')
        if self.delivery == 'project':
            shutil.copytree(ROOT / 'tests/fixtures/diagnostic-analyzer', destination / 'DiagnosticAnalyzer')
            edit(destination / PROJECT, '</Project>', '<ItemGroup><ProjectReference Include="../DiagnosticAnalyzer/DiagnosticAnalyzer.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false" /></ItemGroup></Project>')
        else:
            edit(destination / PROJECT, '</Project>', '<ItemGroup><PackageReference Include="DiagnosticAnalyzer" Version="[1.0.0]" PrivateAssets="all" /></ItemGroup></Project>')
        with (destination / 'App/Program.cs').open('a') as stream:
            stream.write('Console.WriteLine("package=" + Generated.PackageGenerated.Summary);\nclass DiagnosticMarker {}\n')
        with (destination / 'App/.editorconfig').open('a') as stream:
            stream.write('\n[*.cs]\ndotnet_diagnostic.ROLE001.severity = warning\n')

    def generate(self, name, mutation=None):
        graph = super().generate(name, mutation)
        actual = {key: node['targetFramework'] for key, node in self.nodes.items()}
        expected = {key: 'net10.0' for key in self.projects}
        if actual != expected:
            raise AssertionError('SDK-selected configured graph differs: ' + str(actual))
        self.report['configuredFrameworks'] = actual
        return graph

    def ordinary(self, name, mutation=None, fail=False):
        # Base failure oracle is specific to generator GEN diagnostics. Read the
        # independent analyzer oracle here instead.
        if not fail:
            result = super().ordinary(name, mutation)
        else:
            source = self.output / ('ordinary-' + name)
            self.copy(source)
            mutation(source)
            self.restore(source, 'ordinary-' + name)
            process = self.run('ordinary-' + name + '-build', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT,
                '-t:Build', '-p:Configuration=Release', '-nodeReuse:false', '-nologo', '-verbosity:normal'], source, False)
            if process.returncode == 0 or 'error ROLE001' not in process.stdout:
                raise AssertionError('ordinary diagnostic-only analyzer did not fail')
            result = {'returncode': process.returncode}
        log = (self.output / ('ordinary-' + name + '-build.log')).read_text()
        result['analyzerDiagnostic'] = 'error' if 'error ROLE001' in log else 'warning' if 'warning ROLE001' in log else 'none'
        if not fail and not any('/analyzer:' in line and 'DiagnosticAnalyzer.dll' in line for line in log.splitlines()):
            raise AssertionError('diagnostic-only analyzer was not a compiler input')
        return result

    def build(self, name, expected, baseline, fail=False):
        if fail:
            super().build(name, expected, baseline, True)
            record = self.report['cases'][name]
            log = (self.output / (name + '-bazel.log')).read_text()
            if record['returncode'] == 0 or 'error ROLE001' not in log:
                raise AssertionError('adapter diagnostic-only analyzer did not fail')
            bundle = self.generated / ('bazel-bin/node_' + self.nodes['App']['id'] + '.bundle/bundle.json')
            if bundle.exists():
                raise AssertionError('failed analyzer action published a successful bundle')
        else:
            record = super().build(name, expected, baseline)
            log_path = self.output / 'evidence' / name / 'App/build.log'
            log = log_path.read_text() if log_path.exists() else ''
            if log:
                observed = 'warning' if 'warning ROLE001' in log else 'none'
                if observed != baseline['analyzerDiagnostic']:
                    raise AssertionError('ordinary/adapter diagnostic-only analyzer mismatch')
                if '/DiagnosticAnalyzer.dll' not in log:
                    raise AssertionError('diagnostic analyzer missing from compiler inputs')
                if any('/reference:' in token and 'DiagnosticAnalyzer.dll' in token for token in log.split()):
                    raise AssertionError('diagnostic analyzer leaked into references')
        record['analyzerDiagnostic'] = baseline['analyzerDiagnostic']
        self.save()
        return record

    def mutation(self, case):
        def apply(source):
            project = source / PROJECT
            config = source / 'App/.editorconfig'
            if case == 'packageUpgrade':
                edit(project, 'Include="PackageGenerator" Version="[1.0.0]"', 'Include="PackageGenerator" Version="[1.1.0]"')
            elif case == 'analyzerUpgrade':
                if self.delivery == 'project':
                    edit(source / 'DiagnosticAnalyzer/MarkerAnalyzer.cs', '"v1"', '"v2"')
                else:
                    edit(project, 'Include="DiagnosticAnalyzer" Version="[1.0.0]"', 'Include="DiagnosticAnalyzer" Version="[1.1.0]"')
            elif case in ('suppressedAnalyzer', 'errorAnalyzer'):
                edit(config, 'ROLE001.severity = warning', 'ROLE001.severity = ' + ('none' if case == 'suppressedAnalyzer' else 'error'))
            elif case == 'analyzerWarningsAsErrors':
                edit(project, '<OutputType>Exe</OutputType>', '<OutputType>Exe</OutputType><WarningsAsErrors>ROLE001</WarningsAsErrors>')
            elif case == 'recoveredConsumer':
                edit(source / 'App/Program.cs', 'class DiagnosticMarker {}', 'class DiagnosticMarker { public const int Changed = 2; }')
            else:
                mutate(source, case)
        return apply

    def execute(self, cold_only=False):
        self.report['caseSelection'] = 'cold-only' if cold_only else 'full'
        stage = 'acquisition'
        try:
            self.acquire()
            self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
            baseline = self.ordinary('cold')
            if baseline['analyzerDiagnostic'] != 'warning' or 'package-1.0.0' not in baseline['output']:
                raise AssertionError('baseline analyzer/generator behavior absent')
            with BazelSession(self.output) as self.session:
                for name in ('cold', 'unchanged', 'classic', 'packageUpgrade', 'analyzerUpgrade', 'suppressedAnalyzer', 'errorAnalyzer', 'analyzerWarningsAsErrors'):
                    stage = name
                    mutation = None if name in ('cold', 'unchanged') else self.mutation(name)
                    fail = name in ('errorAnalyzer', 'analyzerWarningsAsErrors')
                    ordinary = baseline if mutation is None else self.ordinary(name, mutation, fail)
                    if name == 'packageUpgrade' and 'package-1.1.0' not in ordinary['output']:
                        raise AssertionError('upgraded package generator did not change behavior')
                    if name == 'classic' and '-classic-v2' not in ordinary['output']:
                        raise AssertionError('changed project generator did not change behavior')
                    self.generate(name, mutation)
                    expected = self.projects if name == 'cold' else [] if name == 'unchanged' else ['App']
                    if name == 'classic': expected += ['ClassicGenerator']
                    if name == 'analyzerUpgrade' and self.delivery == 'project': expected += ['DiagnosticAnalyzer']
                    record = self.build(name, expected, ordinary, fail)
                    if name == 'cold': cold = record
                    if name == 'analyzerUpgrade':
                        log = (self.output / 'evidence' / name / 'App/build.log').read_text()
                        if 'Marker declaration observed: v2' not in log: raise AssertionError('upgraded analyzer did not execute')
                    if cold_only: break
            if not cold_only:
                stage = 'relocated'
                remove_tree(self.generated)
                remove_tree(self.base)
                self.generated = self.output / 'recovered-workspace'
                self.base = self.output / 'recovered-base'
                self.source = self.output / 'recovered-preparation'
                with BazelSession(self.output) as self.session:
                    self.generate('relocated')
                    recovered = self.build('relocated', [], baseline)
                    if recovered['bundleFiles'] != cold['bundleFiles'] or len([a for a in recovered['actions'] if a['runner'] == 'disk cache hit']) != len(self.projects):
                        raise AssertionError('all recovered bundles must match cold with explicit disk hits')
                    stage = 'recoveredConsumer'
                    mutation = self.mutation(stage)
                    ordinary = self.ordinary(stage, mutation)
                    self.generate(stage, mutation)
                    self.build(stage, ['App'], ordinary)
            self.report['accepted'] = True
        except BaseException as error:
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.save()
        return self.report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--analyzer-delivery', choices=('project', 'package'), required=True)
    parser.add_argument('--cold-only', action='store_true')
    args = parser.parse_args()
    CombinationProbe(args.output, args.analyzer_delivery).execute(args.cold_only)
