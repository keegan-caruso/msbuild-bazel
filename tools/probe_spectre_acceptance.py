#!/usr/bin/env python3
"""Prepared R05 Spectre acceptance gate; requires framework/package prerequisites."""
import argparse
import json
from pathlib import Path
import shutil

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
    'unreferencedJsonAdd': set(), 'generatorEdit': PROJECTS,
    'relocated': set(), 'recoveredConsumer': {CONSOLE},
}


def mutate(source, case):
    """Mutate source inputs, never rewrite upstream project declarations."""
    if case in ('jsonEdit', 'jsonEntryAdd', 'jsonEntryRemove'):
        path = source / SPINNERS
        data = json.loads(path.read_text())
        if case == 'jsonEdit':
            data['Default']['interval'] += 7
        elif case == 'jsonEntryAdd':
            data['AcceptanceProbe'] = dict(interval=137, unicode=False, frames=['x', 'y'])
        else:
            del data['Ascii']
        path.write_text(json.dumps(data, indent=2) + '\n')
    elif case == 'unreferencedJsonAdd':
        (source / 'src/Spectre.Console/Data/acceptance-unreferenced.json').write_text('{}\n')
    elif case == 'generatorEdit':
        edit(source / ('src/' + GENERATOR + '/Spinners/SpinnerEmitter.cs'),
             'FromMilliseconds({spinner.Interval})', 'FromMilliseconds({spinner.Interval + 1})')
    elif case == 'recoveredConsumer':
        (source / 'src/Spectre.Console/AcceptanceProbe.cs').write_text(
            'namespace Spectre.Console;\ninternal static class AcceptanceProbe { internal const int Value = 2; }\n')
    elif case not in ('cold', 'unchanged', 'relocated'):
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
Console.WriteLine(JsonSerializer.Serialize(new { spinners, colors }));
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
        self.run(destination.name + '-checkout', ['git', 'checkout', '--detach', REVISION], destination)
        actual = self.run(destination.name + '-revision', ['git', 'rev-parse', 'HEAD'], destination).stdout.strip()
        if actual != REVISION:
            raise AssertionError('unexpected source revision')
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
        self.graph = graph
        remove_tree(self.source)

    def observe(self, name, console, ansi):
        result = self.run(name + '-oracle', [DOTNET_ROOT / 'dotnet',
            self.output / 'oracle/bin/Release/net10.0/Oracle.dll', console, ansi], self.output)
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
            source / ('src/' + ANSI + '/bin/Release/net10.0'))
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
        observed = self.observe(name,
            bundles[CONSOLE] / ('artifacts/src/' + CONSOLE + '/bin/Release/net10.0'),
            bundles[ANSI] / ('artifacts/src/' + ANSI + '/bin/Release/net10.0'))
        if observed != baseline:
            raise AssertionError('ordinary and adapter generated behavior differ')
        if self.source.exists():
            raise AssertionError('preparation source survived compilation')
        result = dict(actions=actions, observable=observed, bundleFiles={key: inventory(path) for key, path in bundles.items()},
                      preparationWorkspaceAbsent=True)
        self.report['cases'][name] = result
        self.save()
        return result

    def execute(self, cold_only=False):
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
                for name in list(EXPECTED)[:7]:
                    stage = name
                    ordinary = baseline if name in ('cold', 'unchanged') else self.ordinary(name)
                    if name in ('jsonEdit', 'jsonEntryAdd', 'jsonEntryRemove', 'generatorEdit') and ordinary == baseline:
                        raise AssertionError('mutation failed to change generated behavior')
                    self.generate(name)
                    result = self.build(name, ordinary)
                    if name == 'cold':
                        cold = result
                    if cold_only:
                        self.report['coldAccepted'] = True
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
    args = parser.parse_args()
    SpectreProbe(args.output, args.source, args.packages).execute(args.cold_only)
