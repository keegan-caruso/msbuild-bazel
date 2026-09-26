"""Compile independent apps against two locked versions of the same package."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import urllib.request

root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
w = root / 'workspace'; w.mkdir()
rules = Path(__file__).resolve().parents[2]
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
def put(path, value):
    p = w / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
def call(kind, **attrs):
    return kind + '(' + ','.join(k + '=' + json.dumps(v) for k, v in attrs.items()) + ')\n'
authored = 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")\nload("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
mapping = dict(projects={}, packages={})
reference = urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/netstandard.library.ref/2.1.0/netstandard.library.ref.2.1.0.nupkg').read()
assert hashlib.sha256(reference).hexdigest() == '46ea2fcbd10a817685b85af7ce0c397d12944bdc81209e272de1e05efd33c78a'
(w / 'standard-ref.nupkg').write_bytes(reference)
authored += call('msbuild_nuget_package', name='standard_ref', package_id='NETStandard.Library.Ref', version='2.1.0', archive='standard-ref.nupkg', archive_sha256=hashlib.sha256(reference).hexdigest(), content_hash=base64.b64encode(hashlib.sha512(reference).digest()).decode())
for version in ['1', '2']:
    pack = root / ('pack' + version); pack.mkdir()
    (pack / 'Dependency.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>netstandard2.1</TargetFramework><Version>' + version + '.0.0</Version></PropertyGroup></Project>')
    (pack / 'Value.cs').write_text('public static class Value { public static int Number => ' + version + '; public static int Version' + version + ' => ' + version + '; }')
    subprocess.run([sdk / 'dotnet', 'pack', pack / 'Dependency.csproj', '-c', 'Release', '-o', pack / 'packages', '-p:NuGetAudit=false'], check=True, stdout=subprocess.DEVNULL)
    archive = pack / ('packages/Dependency.' + version + '.0.0.nupkg'); data = archive.read_bytes()
    shutil.copyfile(archive, w / archive.name)
    authored += call('msbuild_nuget_package', name='package' + version, package_id='Dependency', version=version + '.0.0', archive=archive.name, archive_sha256=hashlib.sha256(data).hexdigest(), content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode())
    authored += call('msbuild_package_lock', name='lock' + version, packages=[':package' + version, ':standard_ref'])
    name = 'App' + version
    put(name + '/' + name + '.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><PackageReference Include="Dependency" Version="' + version + '.0.0"/></ItemGroup></Project>')
    put(name + '/Program.cs', 'System.Console.WriteLine(Value.Number);')
    mapping['projects'][name + '/' + name + '.csproj'] = dict(packageLock=':lock' + version)
    mapping['packages']['Dependency/' + version + '.0.0'] = dict(label=':package' + version, roles=['deps'])
# Only Dependency 2.0.0 exists in this closure. Its two parents request
# different minimums; NuGet must retain the locked version with central pinning.
for name, minimum in [('Low', '1.0.0'), ('Bridge', '2.0.0'), ('High', '1.0.0')]:
    dependency = 'Bridge' if name == 'High' else 'Dependency'
    archive = w / (name + '.1.0.0.nupkg')
    with zipfile.ZipFile(archive, 'w') as package:
        package.writestr(name + '.nuspec', '<package><metadata><id>' + name + '</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description><dependencies><group targetFramework="net10.0"><dependency id="' + dependency + '" version="' + minimum + '"/></group></dependencies></metadata></package>')
    data = archive.read_bytes()
    authored += call('msbuild_nuget_package', name=name.lower(), package_id=name, version='1.0.0', archive=archive.name, archive_sha256=hashlib.sha256(data).hexdigest(), content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode(), deps=[':bridge' if name == 'High' else ':package2'])
    mapping['packages'][name + '/1.0.0'] = dict(label=':' + name.lower(), roles=['deps'])
authored += call('msbuild_package_lock', name='diamond_lock', packages=[':low', ':bridge', ':high', ':package2'])
put('Diamond/Directory.Packages.props', '<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally><CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled></PropertyGroup><ItemGroup><PackageVersion Include="Low" Version="1.0.0"/><PackageVersion Include="High" Version="1.0.0"/></ItemGroup></Project>')
put('Diamond/Diamond.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><PackageReference Include="Low"/><PackageReference Include="High"/></ItemGroup></Project>')
put('Diamond/Program.cs', 'System.Console.WriteLine(Value.Number);')
mapping['projects']['Diamond/Diamond.csproj'] = dict(packageLock=':diamond_lock')
put('Multi/Multi.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>netstandard2.1;net10.0</TargetFrameworks></PropertyGroup><ItemGroup><PackageReference Include="Dependency" Version="$(SelectedVersion).0.0"/><Compile Remove="Version*.cs"/><Compile Include="Version$(SelectedVersion).cs"/></ItemGroup></Project>')
for version in ['1', '2']:
    put('Multi/Version' + version + '.cs', 'public static class Multi { public static int Number => Value.Version' + version + '; }')
mapping['projects']['Multi/Multi.csproj'] = dict(properties={'SelectedVersion':'1'}, packageLock=':lock1', frameworkOverrides={'net10.0':dict(properties={'SelectedVersion':'2'},packageLock=':lock2')})
authored += call('msbuild_sync', name='sync', projects=list(mapping['projects']), mappings='sync.json', package_locks=[':lock1', ':lock2', ':diamond_lock'])
put('sync.json', json.dumps(mapping)); put('BUILD.bazel', authored)
put('MODULE.bazel', 'module(name="sync_locks")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules / '.bazelversion', w / '.bazelversion')
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(root / 'base'), '--ignore_all_rc_files']
records = []
def run(name, args, expected=None, error=None, compiled=None):
    execution = root / (name + '.execution.json')
    if args[1] != '//:sync':
        args = args + ['--disk_cache=' + str(root / 'cache'), '--execution_log_json_file=' + str(execution)]
    p = subprocess.run(cmd + args, cwd=w, text=True, capture_output=True)
    output = p.stdout + p.stderr; (root / (name + '.log')).write_text(output)
    assert (p.returncode == 0) if error is None else (p.returncode != 0 and error in output), output[-5000:]
    if expected is not None: assert p.stdout.strip().splitlines()[-1] == expected, output[-2000:]
    if execution.exists():
        text = execution.read_text().strip(); decoder = json.JSONDecoder(); builds = []
        while text:
            row, end = decoder.raw_decode(text); text = text[end:].lstrip()
            if row.get('mnemonic') == 'MSBuildAssembly' and not row.get('cacheHit'): builds.append(row['targetLabel'])
        if compiled is not None: assert sorted(builds) == sorted(compiled), (name, builds, compiled)
        records.append(dict(case=name, compiled=builds))
        (root / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
    print(name, p.returncode, flush=True)
try:
    run('sync', ['run', '//:sync', '--jobs=2'])
    put('BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')
    for version in ['1', '2']:
        run('app' + version, ['run', '//:App' + version + '_App' + version, '--jobs=2'], expected=version)
    run('framework-specific-inputs', ['build', '//:Multi_Multi_netstandard2_1', '//:Multi_Multi_net10_0', '--jobs=2'])
    run('central-transitive-diamond', ['run', '//:Diamond_Diamond', '--jobs=2'], expected='2')
    run('check', ['run', '//:sync', '--', '--check'])
    original = (w / 'projects.generated.bzl').read_bytes()
    mapping['projects']['App2/App2.csproj']['packageLock'] = ':undeclared'
    put('sync.json', json.dumps(mapping))
    run('missing-lock', ['run', '//:sync'], error='declared sync package lock')
    assert (w / 'projects.generated.bzl').read_bytes() == original
    mapping['projects']['App2/App2.csproj']['packageLock'] = ':lock2'
    put('sync.json', json.dumps(mapping))
    run('repair', ['run', '//:sync', '--', '--check'])
    # Upgrade one existing consumer; the other versioned branch stays cached.
    baseline = (w / 'projects.generated.bzl').read_bytes()
    project = (w / 'App1/App1.csproj').read_text()
    put('App1/App1.csproj', project.replace('1.0.0', '2.0.0'))
    saved_package = mapping['packages'].pop('Dependency/2.0.0')
    put('sync.json', json.dumps(mapping))
    run('upgrade-missing-mapping', ['run', '//:sync'], error='exact package mapping')
    mapping['packages']['Dependency/2.0.0'] = saved_package
    assert (w / 'projects.generated.bzl').read_bytes() == baseline
    mapping['projects']['App1/App1.csproj']['packageLock'] = ':lock2'
    put('sync.json', json.dumps(mapping))
    run('upgrade-stale', ['run', '//:sync', '--', '--check'], error='stale')
    assert (w / 'projects.generated.bzl').read_bytes() == baseline
    run('upgrade-sync', ['run', '//:sync'])
    run('upgraded-app', ['run', '//:App1_App1', '--jobs=2'], expected='2', compiled=['//:App1_App1'])
    run('unchanged-app', ['run', '//:App2_App2', '--jobs=2'], expected='2', compiled=[])
    put('App1/App1.csproj', project)
    mapping['projects']['App1/App1.csproj']['packageLock'] = ':lock1'
    put('sync.json', json.dumps(mapping))
    run('upgrade-reverted-sync', ['run', '//:sync'])
    assert (w / 'projects.generated.bzl').read_bytes() == baseline
    run('upgrade-reverted-app', ['run', '//:App1_App1', '--jobs=2'], expected='1', compiled=[])
    run('upgrade-reverted-check', ['run', '//:sync', '--', '--check'])

finally:
    subprocess.run(cmd + ['shutdown'], cwd=w, check=True)
