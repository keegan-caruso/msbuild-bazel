#!/usr/bin/env python3
"""Prepared R05 Spectre acceptance gate; requires framework/package prerequisites."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from bazel_session import BazelSession
from prepare_graph import prepare
from probe_bazel import json_stream
from probe_generator_roles import Probe, ROOT, DOTNET_ROOT, BAZEL, inventory, remove_tree, edit
from probe_graph_cache import cache_environment

REVISION = '2dc90b90add956c2f6777cb659120900ac2eb740'
CONSOLE = 'Spectre.Console'
ANSI = 'Spectre.Console.Ansi'
GENERATOR = 'Spectre.Console.SourceGenerator'
PROJECTS = {CONSOLE, ANSI, GENERATOR}
PROJECT = 'src/' + CONSOLE + '/' + CONSOLE + '.csproj'
SPINNERS = 'src/Spectre.Console/Data/spinners_default.json'
EXPECTED = {
    'cold': PROJECTS, 'unchanged': set(), 'jsonEdit': {CONSOLE},
    'jsonEntryAdd': {CONSOLE}, 'jsonEntryRemove': {CONSOLE},
    'unreferencedJsonAdd': set(), 'additionalFileAdd': {CONSOLE},
    'additionalFileRemove': set(), 'generatorEdit': PROJECTS, 'gitTag': PROJECTS,
    'relocated': set(), 'recoveredConsumer': {CONSOLE},
}


def mutate(source, case):
    """Mutate source inputs, never rewrite upstream project declarations."""
    if case in ('jsonEdit', 'jsonEntryAdd', 'jsonEntryRemove'):
        path = source / (SPINNERS.replace('spinners_default', 'spinners_sindresorhus') if case == 'jsonEntryRemove' else SPINNERS)
        data = json.loads(path.read_text())
        if case == 'jsonEdit':
            data['Default']['interval'] += 7
        elif case == 'jsonEntryAdd':
            data['AcceptanceProbe'] = dict(interval=137, unicode=False, frames=['x', 'y'])
        else:
            del data['dots']
        path.write_text(json.dumps(data, indent=2) + '\n')
    elif case == 'unreferencedJsonAdd':
        (source / 'src/Spectre.Console/Data/acceptance-unreferenced.json').write_text('{}\n')
    elif case == 'additionalFileAdd':
        (source / 'src/Spectre.Console/Data/acceptance-extra.json').write_text('{}\n')
        edit(source / PROJECT, '</Project>', '<ItemGroup><AdditionalFiles Include="Data/acceptance-extra.json" /></ItemGroup></Project>')
    elif case == 'gitTag':
        subprocess.run(['git', 'tag', '1.2.3'], cwd=source, check=True, capture_output=True)
    elif case == 'generatorEdit':
        edit(source / ('src/' + GENERATOR + '/Spinners/SpinnerEmitter.cs'),
             'FromMilliseconds({spinner.Interval})', 'FromMilliseconds({spinner.Interval + 1})')
    elif case == 'recoveredConsumer':
        (source / 'src/Spectre.Console/AcceptanceProbe.cs').write_text(
            'namespace Spectre.Console;\ninternal static class AcceptanceProbe { internal const int Value = 2; }\n')
    elif case not in ('cold', 'unchanged', 'relocated', 'additionalFileRemove'):
        raise ValueError('unknown Spectre case: ' + case)


def verify_actions(actions, expected, strategy, recovered=False):
    names = [action['project'] for action in actions]
    if len(names) != len(set(names)) or not set(names) <= PROJECTS:
        raise AssertionError('duplicate or unknown build actions')
    executed = {action['project'] for action in actions if not action['cacheHit']}
    if executed != set(expected):
        raise AssertionError('unexpected executed projects: ' + str(sorted(executed)))
    for action in actions:
        if not action['cacheHit']:
            if action['runner'] != strategy:
                raise AssertionError('native sandbox required')
            if action.get('compiledProjects') != [action['project']]:
                raise AssertionError('missing compilation evidence or repeated dependency compilation')
    if recovered and (set(names) != PROJECTS or any(
            not action['cacheHit'] or action['runner'] != 'disk cache hit' for action in actions)):
        raise AssertionError('three explicit disk cache recoveries required')


# Reflection keeps the oracle independent of source/generated files. In addition
# to generated API names, compare each spinner's actual interval/frames/unicode.
ORACLE = r'''
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Runtime.Loader;
using System.Text.Json;
var paths = args.Select(Path.GetFullPath).ToArray();
AssemblyLoadContext.Default.Resolving += (_, name) => {
    var file = paths.Select(p => Path.Combine(p, name.Name + ".dll")).FirstOrDefault(File.Exists);
    return file == null ? null : AssemblyLoadContext.Default.LoadFromAssemblyPath(file);
};
var console = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(paths[0], "Spectre.Console.dll"));
var ansi = AssemblyLoadContext.Default.LoadFromAssemblyPath(Path.Combine(paths[1], "Spectre.Console.Ansi.dll"));
var known = console.GetType("Spectre.Console.Spinner+Known", true)!;
var spinners = new SortedDictionary<string, object>();
foreach (var property in known.GetProperties(BindingFlags.Public | BindingFlags.Static)) {
    var spinner = property.GetValue(null)!;
    var type = spinner.GetType();
    spinners[property.Name] = new {
        interval = ((TimeSpan)type.GetProperty("Interval")!.GetValue(spinner)!).TotalMilliseconds,
        frames = (IEnumerable<string>)type.GetProperty("Frames")!.GetValue(spinner)!,
        unicode = (bool)type.GetProperty("IsUnicode")!.GetValue(spinner)!
    };
}
var color = ansi.GetType("Spectre.Console.Color", true)!;
var colors = new SortedDictionary<string, object>();
foreach (var property in color.GetProperties(BindingFlags.Public | BindingFlags.Static).Where(p => p.PropertyType == color)) {
    var value = property.GetValue(null)!;
    colors[property.Name] = new { r = color.GetProperty("R")!.GetValue(value), g = color.GetProperty("G")!.GetValue(value), b = color.GetProperty("B")!.GetValue(value) };
}
var identities = new SortedDictionary<string, object>();
foreach (var name in new[] { "Spectre.Console", "Spectre.Console.Ansi", "Spectre.Console.SourceGenerator" }) {
    var assemblyPath = paths.Select(p => Path.Combine(p, name + ".dll")).First(File.Exists);
    var assembly = AssemblyLoadContext.Default.LoadFromAssemblyPath(assemblyPath);
    using var stream = File.OpenRead(assemblyPath);
    using var pe = new PEReader(stream);
    var entry = pe.ReadDebugDirectory().Single(e => e.Type == DebugDirectoryEntryType.EmbeddedPortablePdb);
    using var provider = pe.ReadEmbeddedPortablePdbDebugDirectoryData(entry);
    var reader = provider.GetMetadataReader();
    var sourceLinks = reader.CustomDebugInformation.Select(h => reader.GetCustomDebugInformation(h))
        .Where(info => reader.GetGuid(info.Kind) == new Guid("CC110556-A091-4D38-9FEC-25AB9A351A6A"))
        .Select(info => JsonDocument.Parse(reader.GetBlobBytes(info.Value)))
        .SelectMany(doc => doc.RootElement.GetProperty("documents").EnumerateObject().Select(p => p.Value.GetString()))
        .Order().ToArray();
    if (sourceLinks.Length == 0 || sourceLinks.Any(url => !url!.Contains("2dc90b90add956c2f6777cb659120900ac2eb740")))
        throw new Exception("Missing pinned-revision SourceLink metadata: " + name);
    identities[name] = new {
        version = assembly.GetName().Version!.ToString(),
        informationalVersion = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion,
        fileVersion = assembly.GetCustomAttribute<AssemblyFileVersionAttribute>()!.Version,
        sourceLinkUrls = sourceLinks
    };
}
Console.WriteLine(JsonSerializer.Serialize(new { spinners, colors, identities }));
'''


class SpectreProbe(Probe):
    projects = PROJECTS

    def __init__(self, output, upstream, packages=None):
        super().__init__(output)
        self.upstream = Path(upstream).resolve()
        self.packages = Path(packages).resolve() if packages else None
        self.report.update(scope='R05-selected-real-Spectre', revision=REVISION,
                           status='prepared-unqualified', acceptanceCaseNames=list(EXPECTED))

    def copy(self, destination):
        # A standalone clone retains MinVer/SourceLink Git inputs, without sharing
        # the original checkout's objects or copying its build output.
        self.run(destination.name + '-clone', ['git', 'clone', '--local', '--no-hardlinks',
            self.upstream, destination], self.output)
        origin = self.run(destination.name + '-original-origin', ['git', 'remote', 'get-url', 'origin'], self.upstream).stdout.strip()
        self.run(destination.name + '-preserve-origin', ['git', 'remote', 'set-url', 'origin', origin], destination)
        self.run(destination.name + '-checkout', ['git', 'checkout', '--detach', REVISION], destination)
        git_identity = dict(origin=origin, shallow=self.run(destination.name + '-shallow', ['git', 'rev-parse', '--is-shallow-repository'], destination).stdout.strip(), tags=self.run(destination.name + '-tags', ['git', 'tag', '--list'], destination).stdout.splitlines())
        prior = self.report.setdefault('gitIdentity', git_identity)
        if prior != git_identity:
            raise AssertionError('source Git origin/history identity changed')
        actual = self.run(destination.name + '-revision', ['git', 'rev-parse', 'HEAD'], destination).stdout.strip()
        if actual != REVISION:
            raise AssertionError('unexpected source revision')
        # Rebuild the baseline index without checkout stat timestamps. Its blob IDs
        # still describe HEAD, so later mutation dirty/untracked semantics survive.
        (destination / '.git/index').unlink()
        self.run(destination.name + '-index', ['git', 'read-tree', 'HEAD'], destination)
        package_root = destination / '.nuget/packages'
        if self.packages:
            shutil.copytree(self.packages, package_root)
        else:
            package_root.mkdir(parents=True)

    def restore(self, source, name):
        # Full ordinary restore preserves netstandard2.0 generator negotiation.
        self.run(name + '-restore', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT, '-t:Restore',
            '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], source)

    def export(self, source, name, success=True):
        request = self.output / (name + '-request.json')
        manifest = self.output / (name + '-manifest.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.400', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties={
                'Configuration': 'Release', 'TargetFramework': 'net10.0'})], output=str(manifest))))
        result = self.run(name + '-export', [DOTNET_ROOT / 'dotnet',
            ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source, success)
        return manifest, result

    def generate(self, name):
        remove_tree(self.source)
        self.copy(self.source)
        mutate(self.source, name)
        self.restore(self.source, name)
        manifest, _ = self.export(self.source, name)
        if list(self.source.glob('src/*/bin/**/*.dll')):
            raise AssertionError('preparation compiled upstream projects')
        remove_tree(self.generated)
        graph = prepare(self.source, manifest, self.generated,
                        environment=cache_environment(self.output, self.source))
        self.nodes = {Path(node['project']).stem: node for node in graph['nodes']}
        if {key: node['targetFramework'] for key, node in self.nodes.items()} != {
                CONSOLE: 'net10.0', ANSI: 'net10.0', GENERATOR: 'netstandard2.0'}:
            raise AssertionError('unexpected selected configured graph')
        if set(self.nodes[CONSOLE]['dependencies']) != {self.nodes[ANSI]['id'], self.nodes[GENERATOR]['id']} or set(self.nodes[ANSI]['dependencies']) != {self.nodes[GENERATOR]['id']} or self.nodes[GENERATOR]['dependencies']:
            raise AssertionError('unexpected Spectre reference scheduling graph')
        additional = [item['path'] for item in self.nodes[CONSOLE]['inputs'] if item['kind'] == 'additional']
        if any(path.endswith('acceptance-extra.json') for path in additional) != (name == 'additionalFileAdd'):
            raise AssertionError('explicit AdditionalFiles membership differs')
        self.report.setdefault('additionalFiles', {})[name] = additional
        self.graph = graph
        remove_tree(self.source)

    def observe(self, name, console, ansi, generator):
        result = self.run(name + '-oracle', [DOTNET_ROOT / 'dotnet',
            self.output / 'oracle/bin/Release/net10.0/Oracle.dll', console, ansi, generator], self.output)
        observed = json.loads(result.stdout)
        if not observed['spinners'] or not observed['colors']:
            raise AssertionError('generated APIs missing')
        return observed

    def ordinary(self, name):
        source = self.output / ('ordinary-' + name)
        self.copy(source)
        mutate(source, name)
        self.restore(source, 'ordinary-' + name)
        self.run('ordinary-' + name + '-build', [DOTNET_ROOT / 'dotnet', 'msbuild', PROJECT,
            '-t:Build', '-p:Configuration=Release', '-p:TargetFramework=net10.0',
            '-nodeReuse:false', '-nologo', '-verbosity:normal'], source)
        result = self.observe('ordinary-' + name,
            source / ('src/' + CONSOLE + '/bin/Release/net10.0'),
            source / ('src/' + ANSI + '/bin/Release/net10.0'),
            source / ('src/' + GENERATOR + '/bin/Release/netstandard2.0'))
        remove_tree(source)
        return result

    def build(self, name, baseline):
        execution = self.output / (name + '-execution.json')
        self.run(name + '-bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.base), '--output_user_root=' + str(self.output / 'bazel-user'),
            'build', '//:node_' + self.nodes[CONSOLE]['id'], '--disk_cache=' + str(self.output / 'disk-cache'),
            '--spawn_strategy=' + self.strategy, '--strategy=MsbuildProject=' + self.strategy,
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all',
            '--execution_log_json_file=' + str(execution)], self.generated)
        actions = []
        evidence = self.output / 'evidence' / name
        evidence.mkdir(parents=True)
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject':
                continue
            identity = record['targetLabel'].split(':node_')[-1]
            project = next(key for key, node in self.nodes.items() if node['id'] == identity)
            action = dict(project=project, cacheHit=record.get('cacheHit', False), runner=record.get('runner'))
            diagnostics = self.generated / ('bazel-bin/node_' + identity + '.diagnostics')
            if diagnostics.is_dir():
                shutil.copytree(diagnostics, evidence / project)
                action['compiledProjects'] = json.loads((diagnostics / 'action.json').read_text())['compiledProjects']
            actions.append(action)
        verify_actions(actions, EXPECTED[name], self.strategy, recovered=name == 'relocated')
        bundles = {key: self.generated / ('bazel-bin/node_' + node['id'] + '.bundle') for key, node in self.nodes.items()}
        for project, bundle in bundles.items():
            payload = json.loads((bundle / 'results.json').read_text())
            expected_framework = 'netstandard2.0' if project == GENERATOR else 'net10.0'
            if payload['targetFramework'] != expected_framework:
                raise AssertionError('replay payload lost selected framework: ' + project)
        observed = self.observe(name,
            bundles[CONSOLE] / ('artifacts/src/' + CONSOLE + '/bin/Release/net10.0'),
            bundles[ANSI] / ('artifacts/src/' + ANSI + '/bin/Release/net10.0'),
            bundles[GENERATOR] / ('artifacts/src/' + GENERATOR + '/bin/Release/netstandard2.0'))
        if observed != baseline:
            raise AssertionError('ordinary and adapter generated behavior differ')
        if self.source.exists():
            raise AssertionError('preparation source survived compilation')
        result = dict(actions=actions, observable=observed, bundleFiles={key: inventory(path) for key, path in bundles.items()},
                      preparationWorkspaceAbsent=True)
        self.report['cases'][name] = result
        self.save()
        return result

    def reject_missing_git_input(self):
        remove_tree(self.source)
        self.copy(self.source)
        self.restore(self.source, 'missingGitInput')
        manifest, _ = self.export(self.source, 'missingGitInput')
        graph = json.loads(manifest.read_text())
        missing = 'workspace/.git/shallow'
        if not all(any(item['path'] == missing for item in node['inputs']) for node in graph['nodes']):
            raise AssertionError('shallow Git input was not declared for every node')
        (self.source / '.git/shallow').unlink()
        destination = self.output / 'missing-git-prepared'
        try:
            prepare(self.source, manifest, destination, environment=cache_environment(self.output, self.source))
        except ValueError as error:
            if not str(error).startswith('missing-input:') or '.git/shallow' not in str(error):
                raise
            if destination.exists():
                raise AssertionError('missing Git input published a prepared workspace')
            self.report['cases']['missingGitInput'] = dict(rejected=True, diagnostic=str(error), published=False)
        else:
            raise AssertionError('missing declared Git input was accepted')
        remove_tree(self.source)
        self.save()

    def execute(self, cold_only=False, git_only=False):
        if git_only:
            self.report.update(scope='R05-Spectre-declared-Git', acceptanceCaseNames=['cold', 'unchanged', 'gitTag', 'missingGitInput'])
        stage = 'bootstrap'
        try:
            self.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
            oracle = self.output / 'oracle'
            oracle.mkdir()
            (oracle / 'Oracle.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
            (oracle / 'Program.cs').write_text(ORACLE)
            self.run('oracle-build', [DOTNET_ROOT / 'dotnet', 'build', '-c', 'Release', '--nologo'], oracle)
            stage = 'ordinary-cold'
            baseline = self.ordinary('cold')
            with BazelSession(self.output) as self.session:
                for name in (['cold', 'unchanged', 'gitTag'] if git_only else list(EXPECTED)[:-2]):
                    stage = name
                    ordinary = baseline if name in ('cold', 'unchanged') else self.ordinary(name)
                    if name in ('jsonEdit', 'jsonEntryAdd', 'jsonEntryRemove', 'generatorEdit', 'gitTag') and ordinary == baseline:
                        raise AssertionError('mutation failed to change generated behavior')
                    if name == 'gitTag' and any(value['version'] != '1.0.0.0' or value['fileVersion'] != '1.2.3.0' or not value['informationalVersion'].startswith('1.2.3+') for value in ordinary['identities'].values()):
                        raise AssertionError('tag did not change actual MinVer assembly identities')
                    self.generate(name)
                    result = self.build(name, ordinary)
                    if name == 'cold':
                        cold = result
                    if cold_only:
                        self.report['coldAccepted'] = True
                        return self.report
            stage = 'missingGitInput'
            self.reject_missing_git_input()
            if git_only:
                self.report.update(accepted=True, status='accepted-native-declared-Git')
                return self.report
            stage = 'relocated'
            old_generated, old_base = self.generated, self.base
            remove_tree(old_generated)
            remove_tree(old_base)
            self.source = self.output / 'recovered-preparation'
            self.generated = self.output / 'recovered-generated'
            self.base = self.output / 'recovered-base'
            with BazelSession(self.output) as self.session:
                self.generate('relocated')
                if old_generated.exists() or old_base.exists() or self.source.exists():
                    raise AssertionError('producer state survived before recovery')
                recovered = self.build('relocated', baseline)
                if recovered['bundleFiles'] != cold['bundleFiles']:
                    raise AssertionError('recovered bundle bytes or modes differ')
                stage = 'recoveredConsumer'
                ordinary = self.ordinary(stage)
                self.generate(stage)
                self.build(stage, ordinary)
            self.report.update(accepted=True, status='accepted-native-selected-graph')
        except BaseException as error:
            self.report['failure'] = dict(stage=stage, type=type(error).__name__, message=str(error))
            raise
        finally:
            self.save()
        return self.report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--packages', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cold-only', action='store_true')
    parser.add_argument('--git-only', action='store_true', help='Run cold/unchanged/tag mutation/missing Git input companion gate')
    args = parser.parse_args()
    SpectreProbe(args.output, args.source, args.packages).execute(args.cold_only, args.git_only)
