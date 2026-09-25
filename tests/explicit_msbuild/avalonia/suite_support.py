"""Pinned test tools and outcome comparison shared by Avalonia qualification."""
from collections import Counter
import hashlib
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
import zipfile


def outcomes(path):
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    results = Counter((r.get('testName'), r.get('outcome'))
                      for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
    assert results, path
    return results


def serialize(results):
    return [list(k) + [v] for k, v in sorted(results.items())]


def test_outcomes(workspace, suite):
    folder = workspace / ('bazel-testlogs/upstream/' + suite + '/test.outputs')
    if (folder / 'results.trx').exists():
        return outcomes(folder / 'results.trx')
    with zipfile.ZipFile(folder / 'outputs.zip') as archive:
        return outcomes(archive.open('results.trx'))


def runner_package(prepared):
    archive = prepared / 'microsoft.testplatform.cli.17.14.1.nupkg'
    if not archive.exists():
        urllib.request.urlretrieve('https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/' + archive.name, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest == '3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
    runner = prepared / 'test-runner'
    with zipfile.ZipFile(archive) as z:
        z.extractall(runner)
    return archive, digest, runner / 'contentFiles/any/net9.0/vstest.console.dll'


def configured_nodes(rows, config, roots):
    by = {row['id']: row for row in rows}
    configured = set()
    def visit(node, context):
        if (node, context) in configured:
            return
        configured.add((node, context))
        row = by[node]
        for edge in row['references']:
            meta = edge['metadata']
            tool = meta.get('ReferenceOutputAssembly', '').lower() == 'false' and meta.get('OutputItemType') != 'Analyzer'
            visit(edge['node'], 'exec' if tool else context)
        bindings = config.get('toolBindings', {}).get(row['id'], config.get('toolBindings', {}).get(row['project'], {}))
        for project in bindings.values():
            candidates = [r['id'] for r in rows if r['id'] == project or r['project'] == project]
            assert len(candidates) == 1, candidates
            visit(candidates[0], 'exec')
    for node in roots:
        visit(node, 'target')
    return configured


def selections(rows, root, labels):
    """Emit explicit choices only for mixed variants in this fixture root's closure."""
    by = {row['id']: row for row in rows}
    closure = set()
    def visit(node):
        for edge in by[node]['references']:
            if edge['metadata'].get('ReferenceOutputAssembly', '').lower() == 'false':
                continue
            child = edge['node']
            if child not in closure:
                closure.add(child)
                visit(child)
    visit(root)
    groups = {}
    for node in closure:
        groups.setdefault(by[node]['project'], []).append(by[node])
    selected = []
    for variants in groups.values():
        if len(variants) > 1:
            matches = [r for r in variants if r['framework'] == by[root]['framework']]
            assert len(matches) == 1, ('Fixture needs an explicit assembly choice', by[root]['project'], variants)
            selected.append(':' + labels[matches[0]['id']])
    return sorted(selected)


def assembly_parity(prepared, output_base, sdk):
    """Compare every configured reference plus embedded resources and XAML methods."""
    import json
    import subprocess
    rules = Path(__file__).resolve().parents[3]
    probe = prepared / 'expanded-inspect'
    probe.mkdir(exist_ok=True)
    (probe / 'Program.cs').write_text((rules / 'tests/explicit_msbuild/avalonia/Inspect.cs.txt').read_text())
    (probe / 'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    subprocess.run([sdk / 'dotnet', 'build', probe / 'Inspect.csproj', '-c', 'Release'], check=True, stdout=subprocess.DEVNULL)
    program = probe / 'bin/Release/net10.0/Inspect.dll'
    def inspect(path):
        return json.loads(subprocess.check_output([sdk / 'dotnet', program, 'inspect', path], text=True))
    def xaml(data):
        return sorted((t['name'], m['name']) for t in data['types'] for m in t['methods'] if '!XamlIl' in m['name'] or t['name'].startswith('CompiledAvaloniaXaml.'))
    labels = json.loads((prepared / 'labels.json').read_text())
    binroot = output_base / 'execroot/_main/bazel-out'
    results = []
    for row in json.loads((prepared / 'inventory.json').read_text()):
        name = row['properties']['AssemblyName']
        label = labels[row['id']]
        raw_root = prepared / 'source' / Path(row['project']).parent
        raw = raw_root / 'obj/Release' / row['framework'] / 'ref' / (name + '.dll')
        references = list(binroot.glob('*/bin/upstream/' + label + '.reference/' + name + '.dll'))
        assert references, label
        for reference in references:
            assert raw.read_bytes() == reference.read_bytes(), ('reference mismatch', label, reference)
        raw_runtime = inspect(raw_root / 'bin/Release' / row['framework'] / (name + '.dll'))
        runtimes = list(binroot.glob('*/bin/upstream/' + label + '.runtime/' + name + '.dll'))
        assert runtimes, label
        for runtime in runtimes:
            actual = inspect(runtime)
            assert raw_runtime['resources'] == actual['resources'], ('resource mismatch', label)
            assert xaml(raw_runtime) == xaml(actual), ('XAML method mismatch', label)
        results.append(dict(label=label,framework=row['framework'],referenceSha256=hashlib.sha256(raw.read_bytes()).hexdigest(),referenceConfigurations=len(references),resources=len(raw_runtime['resources']),compiledXamlMethods=len(xaml(raw_runtime))))
    return results
