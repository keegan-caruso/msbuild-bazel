"""Replay SDK package pruning; the consumer's framework satisfies a package edge."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
w = root / 'workspace'; w.mkdir()
rules = Path(__file__).resolve().parents[2]
def put(path, value):
    p = w / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
# A metadata-only synthetic archive exercises NuGet's SDK-known package identity.
# No framework implementation is replaced, and no package code executes.
archive = w / 'microsoft.aspnetcore.authorization.10.0.11.nupkg'
with zipfile.ZipFile(archive, 'w') as package:
    package.writestr('Microsoft.AspNetCore.Authorization.nuspec', '<package><metadata><id>Microsoft.AspNetCore.Authorization</id><version>10.0.11</version><authors>fixture</authors><description>Pruning metadata fixture</description></metadata></package>')
data = archive.read_bytes()
put('Directory.Build.props', '<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
put('Library/Library.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Microsoft.AspNetCore.Authorization" Version="10.0.11"/></ItemGroup></Project>')
put('Library/Value.cs', 'public static class Value { public static int Number => 7; }')
for name, sdk in [('Web', 'Microsoft.NET.Sdk.Web'), ('Plain', 'Microsoft.NET.Sdk')]:
    put(name + '/' + name + '.csproj', '<Project Sdk="' + sdk + '"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Library/Library.csproj"/></ItemGroup></Project>')
    put(name + '/Program.cs', 'System.Console.WriteLine(Value.Number);')
put('MODULE.bazel', 'module(name="sync_pruning")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules / '.bazelversion', w / '.bazelversion')
authored = '''load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock")
load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
msbuild_nuget_package(name="authorization",package_id="Microsoft.AspNetCore.Authorization",version="10.0.11",archive="microsoft.aspnetcore.authorization.10.0.11.nupkg",archive_sha256=%s,content_hash=%s)
msbuild_package_lock(name="library_lock",packages=[":authorization"])
msbuild_package_lock(name="framework_only",packages=[])
msbuild_sync(name="sync",projects=["Web/Web.csproj","Plain/Plain.csproj"],mappings="sync.json",package_locks=[":library_lock",":framework_only"])
''' % (json.dumps(hashlib.sha256(data).hexdigest()), json.dumps(base64.b64encode(hashlib.sha512(data).digest()).decode()))
put('BUILD.bazel', authored)
put('sync.json', json.dumps(dict(projectDefaults=dict(packageLock=':framework_only'), projects={'Library/Library.csproj':dict(packageLock=':library_lock')}, packages={'Microsoft.AspNetCore.Authorization/10.0.11':dict(label=':authorization', roles=['deps'])})))
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(root / 'base'), '--ignore_all_rc_files']
def run(name, args, error=None):
    p = subprocess.run(cmd + args, cwd=w, text=True, capture_output=True)
    text = p.stdout + p.stderr
    if p.returncode != 0:
        text += '\n'.join(path.read_text() for path in (w / 'bazel-bin').glob('*.diagnostics/build.log'))
    (root / (name + '.log')).write_text(text)
    assert p.returncode == 0 if error is None else p.returncode != 0 and error in text, text[-5000:]
    print(name, p.returncode, flush=True)
    return p.stdout
try:
    run('sync', ['run', '//:sync', '--jobs=2'])
    put('BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')
    assert run('framework-satisfies-package', ['run', '//:Web_Web', '--jobs=2']).strip().splitlines()[-1] == '7'
    run('missing-framework-rejected', ['build', '//:Plain_Plain', '--jobs=2'], error='NU1100')
    project = w / 'Library/Library.csproj'; original = project.read_text()
    project.write_text(original.replace('Version="10.0.11"', 'Version="[10.0.11]"'))
    mapping_path = w / 'sync.json'; mapping = json.loads(mapping_path.read_text())
    mapping['packages']['Microsoft.AspNetCore.Authorization/[10.0.11]'] = mapping['packages'].pop('Microsoft.AspNetCore.Authorization/10.0.11')
    mapping_path.write_text(json.dumps(mapping))
    run('exact-range-sync', ['run', '//:sync'])
    run('exact-range-not-pruned', ['build', '//:Web_Web', '--jobs=2'], error='NU1100')
    project.write_text(original)
    mapping['packages']['Microsoft.AspNetCore.Authorization/10.0.11'] = mapping['packages'].pop('Microsoft.AspNetCore.Authorization/[10.0.11]')
    mapping_path.write_text(json.dumps(mapping))
    run('repair-sync', ['run', '//:sync'])
    assert run('repair', ['run', '//:Web_Web', '--jobs=2']).strip().splitlines()[-1] == '7'
    raw = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet'), 'run', '--project', 'Web/Web.csproj', '-c', 'Release', '--no-launch-profile', '-p:RestoreSources=' + str(w), '-p:RestorePackagesPath=' + str(root / 'raw-packages'), '-p:NuGetAudit=false'], cwd=w, text=True, capture_output=True)
    (root / 'raw.log').write_text(raw.stdout + raw.stderr)
    assert raw.returncode == 0 and raw.stdout.strip().splitlines()[-1] == '7', raw.stdout + raw.stderr
    print('raw-parity', raw.returncode, flush=True)
finally:
    subprocess.run(cmd + ['shutdown'], cwd=w, check=True)
