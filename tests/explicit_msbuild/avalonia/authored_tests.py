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
a = p.parse_args()
a.prepared = a.prepared.resolve()
workspace = a.prepared if a.recover else a.prepared / 'bazel'
instance = workspace / 'authored-instance.txt'
if not a.recover:
    instance.write_text('avalonia-authored/' + a.output.name)
f = RemoteFixture(a.output, a.executor, workspace, instance=instance.read_text())
f.sdk()
target = '//upstream:Avalonia.Generators.Tests'

def outcomes(path):
    ns = {'t': 'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
    results = Counter((r.get('testName'), r.get('outcome'))
                      for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
    assert results, path
    return results

def serialize(results):
    return [list(k) + [v] for k, v in sorted(results.items())]

def remote_outcomes():
    folder = workspace / 'bazel-testlogs/upstream/Avalonia.Generators.Tests/test.outputs'
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
raw = a.prepared / 'source/tests/Avalonia.Generators.Tests/bin/Release/net8.0/Avalonia.Generators.Tests.dll'
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
    if line.startswith(('msbuild_library(name="Avalonia.Generators.Tests",', 'msbuild_binary(name="Avalonia.Generators.Tests",')):
        lines[i] = line.replace(line.split('(')[0] + '(', 'msbuild_test(', 1)[:-1] + ',test_protocol="vstest",test_output_type="exe",test_runner=":authored_runner",test_adapters=[":authored_adapter"],env={"DOTNET_ROLL_FORWARD":"Major"},size="large")'
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
compiled = [('MSBuildAssembly', '//upstream:' + Path(r['project']).stem) for r in rows]
compiled.append(('MSBuildAssembly', '//upstream:DevGenerators'))
source = workspace / 'upstream/src/tools/Avalonia.Generators/Common/XamlXViewResolver.cs'
original = source.read_text()
signature = 'public ResolvedView? ResolveView(string xaml)\n    {'
assert original.count(signature) == 1
try:
    f.run('remote-suite', [target], compiled, cold=True, tests=[target], downloads='all')
    actual = remote_outcomes()
    assert actual == expected, serialize(expected - actual) + serialize(actual - expected)
    reference = workspace / 'bazel-bin/upstream/Avalonia.Generators.reference/Avalonia.Generators.dll'
    before = hashlib.sha256(reference.read_bytes()).hexdigest()
    f.run('noop', [target], [], tests=[], downloads='toplevel')
    source.write_text(original.replace(signature, signature + '\n            if (xaml.Length > 0) throw new InvalidOperationException("remote-authored-negative");'))
    f.run('body-failure', [target], [('MSBuildAssembly', '//upstream:Avalonia.Generators')],
          tests=[target], error='remote-authored-negative', downloads='all')
    failed = remote_outcomes()
    assert any(outcome == 'Failed' for _, outcome in failed)
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == before
    source.write_text(original)
    f.run('restored', [target], [], tests=[], downloads='toplevel')
    assert remote_outcomes() == expected
    f.put('authored-outcomes.json', json.dumps(serialize(expected), indent=2) + '\n')
    report = dict(projects=len(rows),cases=sum(expected.values()),rawAndRemoteNamesAndOutcomesEqual=True,
                  outcomes=dict(Counter(outcome for (_,outcome), count in expected.items() for _ in range(count))),
                  negativeControl=dict(failed=sum(count for (_,outcome),count in failed.items() if outcome == 'Failed'),referenceUnchanged=True))
    (f.folder / 'parity.json').write_text(json.dumps(report, indent=2) + '\n')
finally:
    source.write_text(original)
    f.shutdown()
