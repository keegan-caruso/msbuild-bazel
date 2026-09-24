"""Remote qualification of the prepared Avalonia Simple theme graph.

Run setup.py first. Recovery accepts only the copied Bazel workspace, without
raw build products, local action caches, or producer output directories.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('prepared', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
p.add_argument('--recover', action='store_true')
a = p.parse_args()
a.prepared = a.prepared.resolve()
a.output = a.output.resolve()
rules = Path(__file__).resolve().parents[3]
workspace = a.prepared if a.recover else a.prepared / 'bazel'
instance_file = workspace / 'remote-instance.txt'
if not a.recover:
    instance_file.write_text('avalonia/' + a.output.name)
f = RemoteFixture(a.output, a.executor, workspace, instance=instance_file.read_text())
f.sdk()
target = '//:theme_test'

def products():
    root = f.base / 'execroot/_main/bazel-out'
    files = [p for kind in ['runtime', 'reference']
             for p in root.glob('*/bin/upstream/*.' + kind + '/*.dll')]
    assert len(files) >= 24, files
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}

def test_result(text):
    return next(line for line in text.splitlines() if line.startswith('SimpleTheme styles='))

def remote_result():
    return test_result((f.workspace / 'bazel-testlogs/theme_test/test.log').read_text())

if a.recover:
    try:
        actions = f.run('independent-recovery', [target], [], tests=[])
        assert actions and all(x.get('cacheHit') for x in actions), actions
        assert any(x['mnemonic'] == 'TestRunner' for x in actions)
        assert products() == json.loads((f.workspace / 'expected-products.json').read_text())
    finally:
        f.shutdown()
    raise SystemExit()

build = f.workspace / 'upstream/BUILD.bazel'
lines = build.read_text().splitlines()
lines = [line for line in lines if not line.startswith(('load("@rules_msbuild//msbuild:toolchain', 'msbuild_toolchain(', 'toolchain('))]
lines = [line.replace(',allow_remote_execution=True', '').replace('linux_worker=True', 'linux_worker=True,allow_remote_execution=True') for line in lines]
# The probe lives outside upstream's Directory.Build.* imports.
lines = [line for line in lines if not line.startswith('package(')]
lines.insert(1, 'package(default_visibility=["//visibility:public"])')
build.write_text('\n'.join(lines) + '\n')
f.put('ThemeTest.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="upstream/src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj"/><ProjectReference Include="upstream/src/Avalonia.Remote.Protocol/Avalonia.Remote.Protocol.csproj"/></ItemGroup></Project>')
f.put('ThemeTest.cs', '''using System;
using System.Collections.Generic;
using Avalonia.Remote.Protocol;
using Avalonia.Themes.Simple;
var theme = new SimpleTheme(null);
if (theme.Count != 1) throw new Exception("Compiled XAML did not initialize the theme");
var resolver = new DefaultMessageTypeResolver();
string message;
try { resolver.GetByGuid(Guid.Empty); throw new Exception("Expected a missing GUID"); }
catch (KeyNotFoundException e) {
    message = e.Message;
}
var marker = typeof(DefaultMessageTypeResolver).GetMethod("RemoteQualificationMarker");
Console.WriteLine("SimpleTheme styles=" + theme.Count + "; protocol=" + message + "; api=" + (marker?.Invoke(resolver, null) ?? "absent"));
''')
f.put('BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")
msbuild_test(name="theme_test",project="ThemeTest.csproj",srcs=["ThemeTest.cs"],
    deps=["//upstream:Avalonia.Themes.Simple","//upstream:Avalonia.Remote.Protocol"],
    target_framework="net10.0",linux_worker=True,allow_remote_execution=True)
''')
rows = json.loads((a.prepared / 'inventory.json').read_text())
labels = sorted('//upstream:' + Path(r['project']).stem for r in rows)
assembly = lambda label: ('MSBuildAssembly', label)
leaf = '//upstream:Avalonia.Remote.Protocol'
source = f.workspace / 'upstream/src/Avalonia.Remote.Protocol/DefaultMessageTypeResolver.cs'
original = (a.prepared / 'source/src/Avalonia.Remote.Protocol/DefaultMessageTypeResolver.cs').read_text()
source.write_text(original)
old = 'public Type GetByGuid(Guid id) => _guidsToTypes[id];'
assert original.count(old) == 1
body = original.replace(old, 'public Type GetByGuid(Guid id) => _guidsToTypes.TryGetValue(id, out var type) ? type : throw new KeyNotFoundException("remote-body-edit");')
reference = f.workspace / 'bazel-bin/upstream/Avalonia.Remote.Protocol.reference/Avalonia.Remote.Protocol.dll'
try:
    f.run('cold', [target], [assembly(label) for label in labels + ["//upstream:DevGenerators", target]], cold=True, tests=[target])
    subprocess.run([sys.executable, rules / 'tests/explicit_msbuild/avalonia/verify.py', a.prepared, f.base], check=True)
    # The same executable probe must pass against raw MSBuild's output closure.
    raw = a.prepared / 'raw-probe'
    raw.mkdir(exist_ok=True)
    for name in ['ThemeTest.cs']:
        (raw / name).write_text((f.workspace / name).read_text())
    rawdir = (a.prepared / 'source/src/Avalonia.Themes.Simple/bin/Release/net8.0').resolve()
    (raw / 'ThemeTest.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="' + str(rawdir) + '/*.dll" /></ItemGroup></Project>')
    with (f.folder / 'raw-test.log').open('w') as log:
        subprocess.run([Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet', 'run', '--project', raw / 'ThemeTest.csproj', '-c', 'Release'], cwd=raw, stdout=log, stderr=subprocess.STDOUT, check=True)
    assert remote_result() == test_result((f.folder / 'raw-test.log').read_text())
    before = hashlib.sha256(reference.read_bytes()).hexdigest()
    f.run('noop', [target], [], tests=[])
    source.write_text(body)
    f.run('body', [target], [assembly(leaf)], tests=[target])
    assert remote_result() == 'SimpleTheme styles=1; protocol=remote-body-edit; api=absent'
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == before
    source.write_text(body.replace(old.split(' =>')[0], 'public int RemoteQualificationMarker() => 42;\n        ' + old.split(' =>')[0]))
    # All consumers of the changed reference closure must be reconsidered.
    consumers = [leaf, '//upstream:Avalonia.Controls', '//upstream:Avalonia.Dialogs',
                 '//upstream:Avalonia.Markup.Xaml',
                 '//upstream:Avalonia.Themes.Simple', target]
    f.run('api', [target], [assembly(label) for label in consumers], tests=[target])
    assert remote_result() == 'SimpleTheme styles=1; protocol=remote-body-edit; api=42'
    assert hashlib.sha256(reference.read_bytes()).hexdigest() != before
    f.put('expected-products.json', json.dumps(products(), indent=2) + '\n')
finally:
    f.shutdown()
