#!/usr/bin/env python3
"""Qualify declared Nerdbank/SourceLink inputs through the generated graph."""
import argparse
import json
from pathlib import Path
import shutil

from bazel_session import BazelSession
from prepare_graph import prepare
from probe_bazel import json_stream
from probe_generator_roles import Probe, ROOT, DOTNET_ROOT, BAZEL, inventory, remove_tree
from probe_graph_cache import cache_environment

PROGRAM = r'''
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Text.Json;
var identities = new SortedDictionary<string, object>();
foreach (var assembly in new[] { typeof(Shared.Marker).Assembly, Assembly.GetExecutingAssembly() }) {
    using var stream = File.OpenRead(assembly.Location);
    using var pe = new PEReader(stream);
    var entry = pe.ReadDebugDirectory().Single(e => e.Type == DebugDirectoryEntryType.EmbeddedPortablePdb);
    using var provider = pe.ReadEmbeddedPortablePdbDebugDirectoryData(entry);
    var reader = provider.GetMetadataReader();
    var urls = reader.CustomDebugInformation.Select(h => reader.GetCustomDebugInformation(h))
        .Where(info => reader.GetGuid(info.Kind) == new Guid("CC110556-A091-4D38-9FEC-25AB9A351A6A"))
        .Select(info => JsonDocument.Parse(reader.GetBlobBytes(info.Value)))
        .SelectMany(doc => doc.RootElement.GetProperty("documents").EnumerateObject().Select(p => p.Value.GetString()))
        .Order().ToArray();
    if (urls.Length == 0) throw new Exception("Missing SourceLink");
    identities[assembly.GetName().Name!] = new {
        packageVersion = assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Single(a => a.Key == "ProbeNuGetVersion").Value,
        version = assembly.GetName().Version!.ToString(),
        informationalVersion = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion,
        fileVersion = assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()!.Version,
        sourceLinkUrls = urls
    };
}
Console.WriteLine(JsonSerializer.Serialize(identities));
'''


class VersionProbe(Probe):
    def __init__(self, output, packages, sourcelink_version="10.0.300"):
        super().__init__(output)
        self.packages = Path(packages).resolve()
        self.sourcelink_version = sourcelink_version
        self.report["sourceLinkVersion"] = sourcelink_version
        self.seed = self.output / 'seed'
        self.report['scope'] = 'R05-shared-versioning-net10'

    def git(self, source, *args):
        return self.run('git', ['git', *args], source).stdout.strip()

    def commit(self, source, message):
        self.git(source, 'add', '.')
        self.git(source, '-c', 'user.name=Version Probe', '-c', 'user.email=probe@example.invalid',
                 'commit', '--allow-empty', '-m', message)

    def bootstrap(self):
        self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
        self.seed.mkdir()
        (self.seed / '.gitignore').write_text('bin/\nobj/\n.nuget/\n')
        (self.seed / 'version.json').write_text('{"version":"1.2","publicReleaseRefSpec":["^refs/heads/release$"]}\n')
        (self.seed / 'Directory.Build.props').write_text('''<Project><PropertyGroup>
<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>
<DebugType>embedded</DebugType><RestorePackagesPath>$(MSBuildThisFileDirectory).nuget/packages</RestorePackagesPath>
</PropertyGroup><ItemGroup>
<PackageReference Include="Nerdbank.GitVersioning" Version="3.9.50" PrivateAssets="all" />
<PackageReference Include="Microsoft.SourceLink.GitHub" Version="10.0.300" PrivateAssets="all" />
<PackageReference Include="DotNet.ReproducibleBuilds" Version="2.0.2" PrivateAssets="all" />
<BazelExtraInput Include="$(MSBuildThisFileDirectory)version.json" />
</ItemGroup></Project>'''.replace('Version="10.0.300"', 'Version="' + self.sourcelink_version + '"'))
        (self.seed / 'Directory.Build.targets').write_text('''<Project><Target Name="CapturePackageVersionForProbe" BeforeTargets="GetAssemblyAttributes" DependsOnTargets="GetBuildVersion"><ItemGroup><AssemblyMetadata Include="ProbeNuGetVersion" Value="$(NuGetPackageVersion)" /></ItemGroup></Target></Project>''')
        for project in ('Shared', 'App'):
            folder = self.seed / project
            folder.mkdir()
            body = '<PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Shared/Shared.csproj" /></ItemGroup>' if project == 'App' else ''
            (folder / (project + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk">' + body + '</Project>')
        (self.seed / 'Shared/Marker.cs').write_text('namespace Shared; public class Marker {}\n')
        (self.seed / 'App/Program.cs').write_text(PROGRAM)
        self.git(self.seed, 'init', '-b', 'main')
        self.git(self.seed, 'remote', 'add', 'origin', 'https://github.com/example/version-probe')
        self.commit(self.seed, 'initial version')
        self.commit(self.seed, 'increase height')
        self.report['baselineCommit'] = self.git(self.seed, 'rev-parse', 'HEAD')

    def copy(self, destination, case):
        shutil.copytree(self.seed, destination)
        if case == 'versionConfig':
            (destination / 'version.json').write_text('{"version":"2.3"}\n')
        elif case == 'commit':
            # Reuse a single committed mutation for ordinary and adapter parity.
            self.git(destination, 'reset', '--hard', self.changed_commit)
        elif case == 'releaseBranch':
            self.git(destination, 'checkout', '-b', 'release')
        elif case == 'consumer':
            with (destination / 'App/Program.cs').open('a') as stream:
                stream.write('\n// consumer input mutation\n')
        (destination / '.git/index').unlink()
        self.git(destination, 'read-tree', 'HEAD')
        shutil.copytree(self.packages, destination / '.nuget/packages')

    def properties(self, case):
        return dict(Configuration='Release', NBGV_CacheMode='None', **({'PublicRelease': 'true'} if case == 'releaseOverride' else {}))

    def restore(self, source, name):
        self.run(name + '-restore', [DOTNET_ROOT / 'dotnet', 'restore', 'App/App.csproj'], source)

    def observe(self, name, app):
        return json.loads(self.run(name + '-observe', [DOTNET_ROOT / 'dotnet', app], self.output).stdout)

    def ordinary(self, case):
        source = self.output / ('ordinary-' + case)
        self.copy(source, case)
        self.restore(source, 'ordinary-' + case)
        self.run('ordinary-' + case + '-build', [DOTNET_ROOT / 'dotnet', 'build', 'App/App.csproj', '--no-restore',
            *['-p:' + k + '=' + v for k, v in self.properties(case).items()]], source)
        result = self.observe('ordinary-' + case, source / 'App/bin/Release/net10.0/App.dll')
        remove_tree(source)
        return result

    def export(self, case, default_mode=False):
        request, manifest = (self.output / (case + suffix) for suffix in ('-request.json', '-manifest.json'))
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(self.source), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.400', packageRoot=str(self.source / '.nuget/packages'),
            entryPoints=[dict(project='App/App.csproj', globalProperties=({'Configuration': 'Release'} if default_mode else self.properties(case)))], output=str(manifest))))
        result = self.run(case + '-export', [DOTNET_ROOT / 'dotnet', ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], self.source, success=not default_mode)
        if default_mode:
            assert result.returncode != 0 and 'unsupported-project-reference-role' in result.stdout
            assert not manifest.exists()
        return manifest

    def generate(self, case):
        remove_tree(self.source)
        self.copy(self.source, case)
        self.restore(self.source, case)
        manifest = self.export(case)
        remove_tree(self.generated)
        graph = prepare(self.source, manifest, self.generated, environment=cache_environment(self.output, self.source))
        self.nodes = {Path(n['project']).stem: n for n in graph['nodes']}
        assert set(self.nodes) == {'App', 'Shared'}
        for node in graph['nodes']:
            assert any(i['path'] == 'workspace/version.json' for i in node['inputs'])
        remove_tree(self.source)

    def build(self, case, baseline, expected):
        execution = self.output / (case + '-execution.json')
        self.run(case + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.base), '--output_user_root=' + str(self.output / 'bazel-user'),
            'build', '//:node_' + self.nodes['App']['id'], '--disk_cache=' + str(self.output / 'disk-cache'),
            '--spawn_strategy=' + self.strategy, '--strategy=MsbuildProject=' + self.strategy, '--jobs=2',
            '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all',
            '--execution_log_json_file=' + str(execution)], self.generated)
        actions = []
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject':
                continue
            identity = record['targetLabel'].split(':node_')[-1]
            project = next(k for k, n in self.nodes.items() if n['id'] == identity)
            action = dict(project=project, cacheHit=record.get('cacheHit', False), runner=record.get('runner'))
            if not action['cacheHit']:
                assert action['runner'] == self.strategy
                diagnostics = self.generated / ('bazel-bin/node_' + identity + '.diagnostics/action.json')
                assert json.loads(diagnostics.read_text())['compiledProjects'] == [project]
            actions.append(action)
        assert sorted(a['project'] for a in actions if not a['cacheHit']) == sorted(expected), actions
        if case == 'relocated':
            assert len(actions) == 2 and all(a['cacheHit'] and a['runner'] == 'disk cache hit' for a in actions), actions
        bundles = {k: self.generated / ('bazel-bin/node_' + n['id'] + '.bundle') for k, n in self.nodes.items()}
        observed = self.observe(case, bundles['App'] / 'artifacts/App/bin/Release/net10.0/App.dll')
        assert observed == baseline, (observed, baseline)
        assert not self.source.exists()
        item = dict(actions=actions, observable=observed, preparationWorkspaceAbsent=True,
                    bundleFiles={k: inventory(p) for k, p in bundles.items()})
        self.report['cases'][case] = item
        self.save()
        return item

    def reject_inputs(self):
        for case in ('defaultGraphMode', 'missingHistory', 'missingVersion', 'missingTask', 'corruptTask'):
            remove_tree(self.source)
            self.copy(self.source, 'cold')
            self.restore(self.source, case)
            manifest = self.export(case, default_mode=case == 'defaultGraphMode')
            if case == 'defaultGraphMode':
                self.report['cases'][case] = dict(rejected=True, diagnostic='unsupported-project-reference-role')
                continue
            if case == 'missingHistory':
                parent = self.git(self.source, 'rev-parse', 'HEAD^')
                path = self.source / '.git/objects' / parent[:2] / parent[2:]
            elif case == 'missingVersion':
                path = self.source / 'version.json'
            else:
                path = self.source / '.nuget/packages/nerdbank.gitversioning/3.9.50/build/MSBuildCore/Nerdbank.GitVersioning.Tasks.dll'
            assert path.is_file(), path
            if case == 'corruptTask':
                path.write_bytes(b'corrupt task payload')
            else:
                path.unlink()
            destination = self.output / ('rejected-' + case)
            try:
                prepare(self.source, manifest, destination, environment=cache_environment(self.output, self.source))
            except ValueError as error:
                diagnostic = str(error)
                assert diagnostic.startswith('hash-mismatch:' if case == 'corruptTask' else 'missing-input:'), diagnostic
                assert not destination.exists()
                self.report['cases'][case] = dict(rejected=True, diagnostic=diagnostic, published=False)
            else:
                raise AssertionError('accepted ' + case)
            self.save()
        remove_tree(self.source)

    def execute(self):
        stage = 'bootstrap'
        try:
            self.bootstrap()
            # Keep the mutation object reachable in every copy without changing baseline HEAD.
            baseline_commit = self.report['baselineCommit']
            self.commit(self.seed, 'commit-only mutation')
            self.changed_commit = self.git(self.seed, 'rev-parse', 'HEAD')
            self.git(self.seed, 'reset', '--hard', baseline_commit)
            baseline = self.ordinary('cold')
            source = self.output / 'ordinary-default'
            self.copy(source, 'cold')
            self.restore(source, 'ordinary-default')
            self.run('ordinary-default-build', [DOTNET_ROOT / 'dotnet', 'build', 'App/App.csproj', '--no-restore', '-c', 'Release'], source)
            assert self.observe('ordinary-default', source / 'App/bin/Release/net10.0/App.dll') == baseline
            remove_tree(source)
            self.report['defaultOrdinaryParity'] = True
            with BazelSession(self.output) as self.session:
                for case in ('cold', 'unchanged', 'commit', 'versionConfig', 'releaseOverride', 'releaseBranch'):
                    stage = case
                    ordinary = baseline if case in ('cold', 'unchanged') else self.ordinary(case)
                    if case not in ('cold', 'unchanged'):
                        assert ordinary != baseline, case + ' mutation did not affect version'
                    self.generate(case)
                    result = self.build(case, ordinary, [] if case == 'unchanged' else ['App', 'Shared'])
                    if case == 'cold':
                        cold = result
            stage = 'relocated'
            remove_tree(self.generated)
            remove_tree(self.base)
            self.generated = self.output / 'recovered-generated'
            self.source = self.output / 'recovered-source'
            self.base = self.output / 'recovered-base'
            with BazelSession(self.output) as self.session:
                self.generate(stage)
                recovered = self.build(stage, baseline, [])
                assert recovered['bundleFiles'] == cold['bundleFiles']
                stage = 'consumer'
                ordinary = self.ordinary(stage)
                self.generate(stage)
                self.build(stage, ordinary, ['App'])
            stage = 'input rejection controls'
            self.reject_inputs()
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
    parser.add_argument('--sourcelink-version', choices=('8.0.0', '10.0.300'), default='10.0.300')
    args = parser.parse_args()
    VersionProbe(args.output, args.packages, args.sourcelink_version).execute()
