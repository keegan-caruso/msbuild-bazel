#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 - <<'PY'
from pathlib import Path
import hashlib,json
Path('NuGet.Config').write_text('<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
Path('Directory.Build.targets').write_text("""<Project><Target Name="CheckBoundSdk" BeforeTargets="BeforeBuild"><Error Condition="$([MSBuild]::NormalizeDirectory('$(NetCoreSdkRoot)')) != $([MSBuild]::NormalizeDirectory('$(MSBuildBinPath)'))" Text="Selected SDK directory was not bound"/></Target></Project>""")
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'documents':{'Directory.Build.targets':dict(sha256=hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),targets=['CheckBoundSdk'],tasks=[],inputs=[])}}}))
Path('Directory.Build.props').write_text('<Project><PropertyGroup><BaseIntermediateOutputPath>obj/$(MSBuildProjectName)/</BaseIntermediateOutputPath><BaseOutputPath>bin/$(MSBuildProjectName)/</BaseOutputPath><DefaultItemExcludes>$(DefaultItemExcludes);obj/**;bin/**</DefaultItemExcludes></PropertyGroup></Project>')
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="12.0.3"/></ItemGroup></Project>'))
Path('Library/Other.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3"/></ItemGroup></Project>')
p=Path('App/App.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><ProjectReference Include="../Library/Other.csproj"/></ItemGroup></Project>'))
Path('BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl","msbuild_nuget_update")\nmsbuild_nuget_update(name="update_packages",projects=["App/App.csproj","Tests/Tests.csproj"],mappings="mappings.json")\n')
PY
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'PY'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text())
for name,version in [('Library','12.0.3'),('Other','13.0.3')]:
    lock='Library/packages.'+name+'.lock.json';assert lock in m['lockFiles']
    assert json.loads(Path(lock).read_text())['dependencies']['net10.0']['Newtonsoft.Json']['resolved']==version
assert not Path('Library/packages.lock.json').exists()
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nnuget=use_extension("@rules_msbuild//msbuild:nuget.bzl","nuget")\nnuget.lock(name="nuget",lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
p=Path('BUILD.bazel');p.write_text(p.read_text()+'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nmsbuild_sync(name="sync",projects=["App/App.csproj","Tests/Tests.csproj"],package_lock="@nuget//:packages",package_build=True,mappings="mappings.json")\n')
PY
bazel run //:sync
bazel run //:sync -- --check
cat >> BUILD.bazel <<'BZL'
load(":graph.generated.bzl","app_graph")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_test")
app_graph(name="graph")
msbuild_graph_test(name="test",graph=":graph",project="Tests/Tests.csproj")
BZL
bazel test //:test --test_output=errors
cp graph.generated.json "$TEST_TMPDIR/contract.before"
python3 - <<'PY'
from pathlib import Path
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('12.0.3','13.0.3'))
PY
if bazel run //:sync > "$TEST_TMPDIR/stale.log" 2>&1; then echo 'Accepted stale project-specific native lock' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/stale.log" 'NU1004'
cmp graph.generated.json "$TEST_TMPDIR/contract.before"
cp nuget.lock.json "$TEST_TMPDIR/inventory.before"
python3 - <<'PY'
from pathlib import Path
for name in ['Name Space','Name_Space']:
    Path('Library/'+name+'.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup></Project>')
p=Path('App/App.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><ProjectReference Include="../Library/Name Space.csproj"/><ProjectReference Include="../Library/Name_Space.csproj"/></ItemGroup></Project>'))
PY
if bazel run //:update_packages > "$TEST_TMPDIR/collision.log" 2>&1; then echo 'Accepted colliding native lock names' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/collision.log" 'Project-specific NuGet lock names collide'
cmp nuget.lock.json "$TEST_TMPDIR/inventory.before"
echo 'PASS: shared-directory native locks, SDK binding, dependency drift and atomic collision rejection'
