"""Raw/remote parity and invalidation for Avalonia's authored generator suite."""
import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('prepared', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--recover', action='store_true')
p.add_argument('--suite', choices=['generator', 'markup'], default='generator')
a = p.parse_args()
a.prepared = a.prepared.resolve()
workspace = a.prepared if a.recover else a.prepared / 'bazel'
instance = workspace / 'authored-instance.txt'
if not a.recover:
    instance.write_text('avalonia-authored/' + a.output.name)
f = RemoteFixture(a.output, a.executor, workspace, instance=instance.read_text())
f.sdk()
suite = 'Avalonia.Generators.Tests' if a.suite == 'generator' else 'Avalonia.Markup.UnitTests'
target = '//upstream:' + suite

def outcomes(path):
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    results = Counter((r.get('testName'), r.get('outcome'))
                      for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
    assert results, path
    return results

def serialize(results):
    return [list(k) + [v] for k, v in sorted(results.items())]

def remote_outcomes():
    folder = workspace / ('bazel-testlogs/upstream/' + suite + '/test.outputs')
    # Bazel may zip undeclared outputs, depending on the selected baseline.
    if (folder / 'results.trx').exists():
        return outcomes(folder / 'results.trx')
    with zipfile.ZipFile(folder / 'outputs.zip') as archive:
        return outcomes(archive.open('results.trx'))

if a.recover:
    try:
        actions = f.run('independent-recovery', [target], [], tests=[], downloads='toplevel')
        assert actions and all(x['cacheHit'] for x in actions)
        assert any(x['mnemonic'] == 'TestRunner' for x in actions)
        assert serialize(remote_outcomes()) == json.loads((workspace / 'authored-outcomes.json').read_text())
    finally:
        f.shutdown()
    raise SystemExit()

sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'
archive = a.prepared / 'microsoft.testplatform.cli.17.14.1.nupkg'
if not archive.exists():
    urllib.request.urlretrieve('https://api.nuget.org/v3-flatcontainer/microsoft.testplatform.cli/17.14.1/' + archive.name, archive)
data = archive.read_bytes()
digest = hashlib.sha256(data).hexdigest()
assert digest == '3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
runner = a.prepared / 'test-runner'
with zipfile.ZipFile(archive) as z:
    z.extractall(runner)
raw = a.prepared / ('source/tests/' + suite + '/bin/Release/net8.0/' + suite + '.dll')
raw_results = a.prepared / 'authored-raw'
with (f.folder / 'raw-tests.log').open('w') as log:
    subprocess.run([sdk, runner / 'contentFiles/any/net9.0/vstest.console.dll', raw,
                    '/Logger:trx;LogFileName=results.trx', '/ResultsDirectory:' + str(raw_results)],
                   env=dict(os.environ, DOTNET_ROLL_FORWARD='Major'), stdout=log, stderr=subprocess.STDOUT, check=True)
expected = outcomes(raw_results / 'results.trx')
assert {outcome for _, outcome in expected} == {'Passed'}
shutil.copyfile(archive, workspace / 'upstream/locked-packages' / archive.name)
build = workspace / 'upstream/BUILD.bazel'
snapshot = a.prepared / 'authored-build.original'
if not snapshot.exists():
    assert 'authored_runner_package' not in build.read_text(), 'Start from a fresh prepared fixture'
    snapshot.write_text(build.read_text())
lines = snapshot.read_text().splitlines()
lines = [line for line in lines if not line.startswith(('load("@rules_msbuild//msbuild:toolchain', 'msbuild_toolchain(', 'toolchain('))]
lines = [line.replace(',allow_remote_execution=True', '').replace('linux_worker=True', 'linux_worker=True,allow_remote_execution=True') for line in lines]
lines.insert(0, 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_test","msbuild_test_tool")')
for i, line in enumerate(lines):
    if line.startswith(('msbuild_library(name="' + suite + '",', 'msbuild_binary(name="' + suite + '",')):
        lines[i] = line.replace(line.split('(')[0] + '(', 'msbuild_test(', 1)[:-1] + ',test_protocol="vstest",test_output_type="' + ('exe' if a.suite == 'generator' else 'library') + '",test_runner=":authored_runner",test_adapters=[":authored_adapter"],env={"DOTNET_ROLL_FORWARD":"Major"},size="large")'
        break
else:
    raise AssertionError('Prepared graph must contain the authored test project')
lines += [
    'msbuild_nuget_package(name="authored_runner_package",package_id="Microsoft.TestPlatform.CLI",version="17.14.1",archive="locked-packages/' + archive.name + '",archive_sha256="' + digest + '",content_hash="' + base64.b64encode(hashlib.sha512(data).digest()).decode() + '")',
    'msbuild_test_tool(name="authored_runner",package=":authored_runner_package",path="contentFiles/any/net9.0/vstest.console.dll")',
    'msbuild_test_tool(name="authored_adapter",package=":archive_xunit.runner.visualstudio_2.8.2",path="build/net6.0")',
]
build.write_text('\n'.join(lines) + '\n')
rows = json.loads((a.prepared / 'inventory.json').read_text())
labels = json.loads((a.prepared / 'labels.json').read_text())
by = {row['id']: row for row in rows}
# Track the execution transition on tools, including dependencies shared with
# the target configuration. Analyzers retain their declared configuration.
configured = set()
def visit(node, context):
    if (node, context) in configured:
        return
    configured.add((node, context))
    row = by[node]
    for edge in row['references']:
        metadata = edge['metadata']
        tool = metadata.get('ReferenceOutputAssembly', '').lower() == 'false' and metadata.get('OutputItemType') != 'Analyzer'
        visit(edge['node'], 'exec' if tool else context)
    bindings = json.loads((a.prepared / 'config.json').read_text()).get('toolBindings', {}).get(row['project'], {})
    for project in bindings.values():
        candidates = [r['id'] for r in rows if r['project'] == project]
        assert len(candidates) == 1, candidates
        visit(candidates[0], 'exec')
for row in rows:
    if row['entry']:
        visit(row['id'], 'target')
compiled = [('MSBuildAssembly', '//upstream:' + labels[node]) for node, _ in configured]
if a.suite == 'generator':
    source = workspace / 'upstream/src/tools/Avalonia.Generators/Common/XamlXViewResolver.cs'
    signature = 'public ResolvedView? ResolveView(string xaml)\n    {'
    negative = '\n            if (xaml.Length > 0) throw new InvalidOperationException("remote-authored-negative");'
    changed = [r['id'] for r in rows if Path(r['project']).stem == 'Avalonia.Generators']
else:
    # Only choose among variants actually present in the declared dependency
    # graph. These are fixture declarations, never a production preference.
    groups = {}
    for row in rows:
        groups.setdefault(row['project'], []).append(row)
    selected = []
    for variants in groups.values():
        if len(variants) > 1:
            modern = [r for r in variants if r['framework'] == 'net8.0']
            assert len(modern) == 1, variants
            selected.append(':' + labels[modern[0]['id']])
    build.write_text(build.read_text().replace('msbuild_test(name="' + suite + '",',
        'msbuild_test(name="' + suite + '",assembly_selections=' + json.dumps(selected) + ','))
    source = workspace / 'upstream/src/Markup/Avalonia.Markup/Data/Binding.cs'
    signature = 'public Binding()\n        {'
    negative = '\n            throw new InvalidOperationException("remote-authored-negative");'
    changed = [r['id'] for r in rows if Path(r['project']).stem == 'Avalonia.Markup']
original = source.read_text()
assert original.count(signature) == 1
body_compiled = [('MSBuildAssembly', '//upstream:' + labels[node]) for node, _ in configured if node in changed]

try:
    f.run('remote-suite', [target], compiled, cold=True, tests=[target], downloads='all')
    actual = remote_outcomes()
    assert actual == expected, serialize(expected - actual) + serialize(actual - expected)
    references = {labels[node]: workspace / ('bazel-bin/upstream/' + labels[node] + '.reference/' + by[node]['properties']['AssemblyName'] + '.dll') for node in changed}
    def reference_hashes():
        return {label: hashlib.sha256(path.read_bytes()).hexdigest() for label, path in references.items()}
    before = reference_hashes()
    f.run('noop', [target], [], tests=[], downloads='toplevel')
    source.write_text(original.replace(signature, signature + negative))
    f.run('body-failure', [target], body_compiled,
          tests=[target], error='remote-authored-negative', downloads='all')
    failed = remote_outcomes()
    assert any(outcome == 'Failed' for _, outcome in failed)
    assert reference_hashes() == before
    source.write_text(original)
    f.run('restored', [target], [], tests=[], downloads='toplevel')
    assert remote_outcomes() == expected
    if a.suite == 'markup':
        # An API addition propagates through compiler references. Unchanged
        # downstream references stop propagation unless another direct changed
        # reference is in that consumer's transitive compiler closure.
        affected = set(changed)
        while True:
            expanded = affected | {r['id'] for r in rows if any(e['node'] in affected for e in r['references'])}
            if expanded == affected:
                break
            affected = expanded
        api_compiled = [('MSBuildAssembly', '//upstream:' + labels[node]) for node, _ in configured if node in affected]
        source.write_text(original.replace('public class Binding : BindingBase\n    {',
            'public class Binding : BindingBase\n    {\n        /// <summary>Qualification API addition.</summary>\n        public static int QualificationMarker() => 42;'))
        f.run('api-edit', [target], api_compiled, tests=[target], downloads='all')
        assert remote_outcomes() == expected
        source.write_text(original)
        f.run('api-restored', [target], [], tests=[], downloads='toplevel')
        assert remote_outcomes() == expected
    f.put('authored-outcomes.json', json.dumps(serialize(expected), indent=2) + '\n')
    report = dict(projects=len(rows),cases=sum(expected.values()),rawAndRemoteNamesAndOutcomesEqual=True,
                  outcomes=dict(Counter(outcome for (_,outcome), count in expected.items() for _ in range(count))),
                  negativeControl=dict(failed=sum(count for (_,outcome),count in failed.items() if outcome == 'Failed'),referenceUnchanged=True,referenceHashes=before))
    (f.folder / 'parity.json').write_text(json.dumps(report, indent=2) + '\n')
finally:
    source.write_text(original)
    f.shutdown()
