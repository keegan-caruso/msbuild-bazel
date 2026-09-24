"""Remote facade selection, aggregate tests, edit isolation and cached recovery."""
import argparse
import base64
import hashlib
from pathlib import Path
import urllib.request
from remote_support import RemoteFixture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--executor', required=True)
a = p.parse_args()
f = RemoteFixture(a.output, a.executor, instance='project-facades/' + a.output.name)
f.sdk()
archive = urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/netstandard.library.ref/2.1.0/netstandard.library.ref.2.1.0.nupkg', timeout=60).read()
digest = hashlib.sha256(archive).hexdigest()
assert digest == '46ea2fcbd10a817685b85af7ce0c397d12944bdc81209e272de1e05efd33c78a'
(f.workspace / 'ref.nupkg').write_bytes(archive)
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>{}</TargetFrameworks>{}</PropertyGroup>{}</Project>'
f.put('Multi/Multi.csproj', project.format('netstandard2.1;net10.0;net10.0-windows', '', ''))
f.put('Portable/Portable.csproj', project.format('netstandard2.1', '', ''))
f.put('Portable/Value.cs', 'public static class Portable { public static int Value => 3; }')
source = '''public static partial class Multi { public static int Value() {
#if WINDOWS
return 11;
#elif NET10_0
return ModernValue();
#else
return 2;
#endif
} }
'''
f.put('Multi/Value.cs', source)
modern = 'public static partial class Multi { private static int ModernValue() => 10; }'
f.put('Multi/Modern.cs', modern)
f.put('Tests/Tests.csproj', project.format('net10.0;net10.0-windows', '<OutputType>Exe</OutputType>', '<ItemGroup><ProjectReference Include="../Multi/Multi.csproj"/><ProjectReference Include="../Portable/Portable.csproj"/></ItemGroup>'))
f.put('Tests/Program.cs', '''int expected =
#if WINDOWS
11;
#else
10;
#endif
System.Console.WriteLine($"value={Multi.Value()},portable={Portable.Value}");
return Multi.Value() == expected && Portable.Value == 3 ? 0 : 1;
''')
f.put('BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_project", "msbuild_test_project", "msbuild_nuget_package", "msbuild_package_lock")
msbuild_project(name="Multi",project="Multi/Multi.csproj",srcs=["Multi/Value.cs"],target_frameworks=["netstandard2.1","net10.0","net10.0-windows"],framework_overrides={"netstandard2.1":{"package_lock":":standard_lock"},"net10.0":{"srcs":["Multi/Modern.cs"]}},linux_worker=True,allow_remote_execution=True)
msbuild_project(name="Portable",project="Portable/Portable.csproj",srcs=["Portable/Value.cs"],target_frameworks=["netstandard2.1"],package_lock=":standard_lock",linux_worker=True,allow_remote_execution=True)
msbuild_test_project(name="Tests",project="Tests/Tests.csproj",srcs=["Tests/Program.cs"],target_frameworks=["net10.0","net10.0-windows"],deps=[":Multi"],framework_overrides={"net10.0":{"deps":[":Portable"]},"net10.0-windows":{"deps":[":Portable_netstandard2_1"]}},use_apphost=False,linux_worker=True,allow_remote_execution=True)
msbuild_package_lock(name="standard_lock",packages=[":standard_pack"])
''' + 'msbuild_nuget_package(name="standard_pack",package_id="NETStandard.Library.Ref",version="2.1.0",archive="ref.nupkg",archive_sha256="' + digest + '",content_hash="' + base64.b64encode(hashlib.sha512(archive).digest()).decode() + '")\n')

def compiled(*names):
    return [('MSBuildAssembly', '//:' + name) for name in names]

def ref_hash():
    return hashlib.sha256((f.workspace / 'bazel-bin/Multi_net10_0.reference/Multi.dll').read_bytes()).hexdigest()

try:
    # Analyzed standard variant must not execute just because the facade exposes it.
    f.run('selected', ['//:Tests_net10_0'], compiled('Multi_net10_0', 'Portable_netstandard2_1', 'Tests_net10_0'), tests=['//:Tests_net10_0'])
    before = ref_hash()
    f.run('suite', ['//:Tests'], compiled('Multi_net10_0-windows', 'Tests_net10_0-windows'), tests=['//:Tests_net10_0-windows'])
    f.run('noop', ['//:Tests'], [], tests=[])
    f.put('Multi/Value.cs', source.replace('return ModernValue();', 'return ModernValue() + 1;'))
    # Both selected variants receive the shared source edit, including its PDB
    # document checksum. Both tests rerun, while consumers do not recompile.
    f.run('body-failure', ['//:Tests'], compiled('Multi_net10_0', 'Multi_net10_0-windows'), tests=['//:Tests_net10_0', '//:Tests_net10_0-windows'], error='FAIL')
    assert ref_hash() == before
    f.put('Multi/Value.cs', source)
    f.run('restore', ['//:Tests'], [], tests=[])
    f.put('Multi/Modern.cs', modern.replace('=> 10;', '=> 99;'))
    f.run('variant-only-failure', ['//:Tests'], compiled('Multi_net10_0'), tests=['//:Tests_net10_0'], error='FAIL')
    assert ref_hash() == before
    f.put('Multi/Modern.cs', modern)
    f.run('variant-restored', ['//:Tests'], [], tests=[])
    # Building the facade itself intentionally builds every variant.
    f.run('aggregate', ['//:Multi'], compiled('Multi_netstandard2_1'), command='build')
    f.shutdown()
    f.base = f.folder / 'fresh-base'
    actions = f.run('fresh-recovery', ['//:Tests'], [], tests=[], downloads='toplevel')
    assert actions and all(action['cacheHit'] for action in actions)
    assert {x['targetLabel'] for x in actions if x['mnemonic'] == 'TestRunner'} == {'//:Tests_net10_0', '//:Tests_net10_0-windows'}
finally:
    f.put('Multi/Value.cs', source)
    f.put('Multi/Modern.cs', modern)
    f.shutdown()
