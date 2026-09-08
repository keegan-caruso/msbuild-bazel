#!/usr/bin/env python3
"""Ordinary pinned Spectre baseline; no adapter execution or project rewrites."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

REVISION = '2dc90b90add956c2f6777cb659120900ac2eb740'
PROJECTS = {'Spectre.Console': 'net10.0', 'Spectre.Console.Ansi': 'net10.0',
            'Spectre.Console.SourceGenerator': 'netstandard2.0'}


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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    dotnet = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'
    env = dict(os.environ, NUGET_PACKAGES=str(source / '.nuget/packages'),
               DOTNET_CLI_HOME=str(output / 'home'), DOTNET_NOLOGO='1',
               DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1')

    def run(name, command, cwd=source):
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / (name + '.log')).write_text(result.stdout)
        if result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(output / (name + '.log')))
        return result.stdout.strip()

    run('clone', ['git', 'clone', '--local', '--no-hardlinks', args.source, source], output)
    origin = run('original-origin', ['git', 'remote', 'get-url', 'origin'], args.source)
    run('preserve-origin', ['git', 'remote', 'set-url', 'origin', origin])
    run('checkout', ['git', 'checkout', '--detach', REVISION])
    assert run('revision', ['git', 'rev-parse', 'HEAD']) == REVISION
    shutil.copytree(args.packages, source / '.nuget/packages')
    entry = 'src/Spectre.Console/Spectre.Console.csproj'
    run('restore', [dotnet, 'msbuild', entry, '-t:Restore', '-p:Configuration=Release',
                    '-nodeReuse:false', '-nologo'])
    command = [dotnet, 'msbuild', entry, '-t:Build', '-p:Configuration=Release',
               '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo', '-verbosity:normal']
    run('cold-build', command)
    unchanged = run('unchanged-build', command)
    assert unchanged.count('Skipping target \"CoreCompile\"') == 3
    report = dict(revision=REVISION, sdkVersion=run('sdk', [dotnet, '--version']),
                  scope='ordinary-selected-Spectre-macOS', projects={})
    for name, framework in PROJECTS.items():
        project = 'src/' + name + '/' + name + '.csproj'
        value = run(name + '-identity', [dotnet, 'msbuild', project, '-t:Build',
            '-p:Configuration=Release', '-p:TargetFramework=' + framework, '-nodeReuse:false',
            '-getProperty:Version,AssemblyVersion,FileVersion,InformationalVersion,RepositoryUrl,RepositoryCommit,SourceRevisionId,MSBuildAllProjects',
            '-getItem:Analyzer,AdditionalFiles,Compile,ProjectReference'])
        report['projects'][name] = json.loads(value[value.index('{'):])
        run(name + '-preprocessed', [dotnet, 'msbuild', project, '-p:Configuration=Release',
            '-p:TargetFramework=' + framework, '-preprocess:' + str(output / (name + '.xml'))])
        assets = source / 'src' / name / 'obj/project.assets.json'
        data = json.loads(assets.read_text())
        report['projects'][name]['restoredPackages'] = sorted(data['libraries'])
        report['projects'][name]['sourceLink'] = [json.loads(p.read_text()) for p in
            (source / 'src' / name / 'obj').rglob('*.sourcelink.json')]
    oracle = output / 'oracle'
    oracle.mkdir()
    (oracle / 'Oracle.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
    (oracle / 'Program.cs').write_text(ORACLE)
    run('oracle-build', [dotnet, 'build', '-c', 'Release', '--nologo'], oracle)
    report['observable'] = json.loads(run('oracle', [dotnet, oracle / 'bin/Release/net10.0/Oracle.dll',
        source / 'src/Spectre.Console/bin/Release/net10.0',
        source / 'src/Spectre.Console.Ansi/bin/Release/net10.0']))
    report['shallowRepository'] = run('shallow', ['git', 'rev-parse', '--is-shallow-repository'])
    report['tags'] = run('tags', ['git', 'tag', '--list']).splitlines()
    report['gitStatus'] = run('git-status', ['git', 'status', '--porcelain'])
    report['gitMetadata'] = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in (source / '.git').rglob('*') if p.is_file()}
    assert report['sdkVersion'] == '10.0.400'
    for project in report['projects'].values():
        assert project['Properties']['SourceRevisionId'] == REVISION
        assert project['Properties']['InformationalVersion'].endswith('+' + REVISION)
        assert project['sourceLink'] and all(link['documents'] for link in project['sourceLink'])
    report['accepted'] = bool(report['observable']['spinners'] and report['observable']['colors']
                              and not report['gitStatus'])
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    assert report['accepted']
    print(output / 'report.json')


if __name__ == '__main__':
    main()
