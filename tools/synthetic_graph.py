"""Deterministic, package-free C16 graphs. Indices are a topological ordering."""
import json
from pathlib import Path

MODULUS = 1000000007


def topology(count, shape):
    if count < 2 or shape not in ('chain', 'fan'):
        raise ValueError('count must be at least two; shape must be chain or fan')
    edges = [[]]
    if shape == 'chain':
        edges += [[i - 1] for i in range(1, count)]
    else:
        edges += [[(i - 1) // 2] for i in range(1, count - 1)]
        parents = {d for dependencies in edges for d in dependencies}
        edges.append([i for i in range(count - 1) if i not in parents])
    return edges


def name(index):
    return f'N{index:04d}'


def project(index):
    return f'{name(index)}/{name(index)}.csproj'


def consumers(edges, changed):
    result = {changed}
    for index, dependencies in enumerate(edges):
        if result.intersection(dependencies): result.add(index)
    return result


def oracle(edges, changed=None):
    values = []
    for index, dependencies in enumerate(edges):
        values.append((index + 1 + (7 if index == changed else 0) + sum(values[d] for d in dependencies)) % MODULUS)
    return str(values[-1])


def source(index, dependencies, entry, changed=False):
    expression = ' + '.join([str(index + 1 + (7 if changed else 0)) + 'L'] + [f'{name(d)}.Value.Read()' for d in dependencies])
    main = f'public static void Main() => System.Console.WriteLine(Read());' if entry else ''
    return f'namespace {name(index)}; public static class Value {{ public static long Read() => ({expression}) % {MODULUS}L; {main} }}\n'


def generate(workspace, count=10, shape='fan', changed=None):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=False)
    edges = topology(count, shape)
    (workspace / 'global.json').write_text('{"sdk":{"version":"10.0.100","rollForward":"disable"}}\n')
    (workspace / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources></configuration>\n')
    (workspace / 'Directory.Build.props').write_text('<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework><UseAppHost>false</UseAppHost><UseSharedCompilation>false</UseSharedCompilation><EnableNETAnalyzers>false</EnableNETAnalyzers><Deterministic>true</Deterministic><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup></Project>\n')
    for index, dependencies in enumerate(edges):
        directory = workspace / name(index)
        directory.mkdir()
        references = ''.join(f'<ProjectReference Include="../{project(d)}"/>' for d in dependencies)
        output_type = '<PropertyGroup><OutputType>Exe</OutputType></PropertyGroup>' if index == count - 1 else ''
        (workspace / project(index)).write_text(f'<Project Sdk="Microsoft.NET.Sdk">{output_type}<ItemGroup>{references}</ItemGroup></Project>\n')
        (directory / 'Value.cs').write_text(source(index, dependencies, index == count - 1, index == changed))
    (workspace / '.nuget/packages').mkdir(parents=True)
    protocol = dict(schemaVersion=1, count=count, shape=shape, edges=edges, entry=project(count - 1), expectedOutput=oracle(edges, changed))
    (workspace / 'synthetic.json').write_text(json.dumps(protocol, indent=2) + '\n')
    return protocol
