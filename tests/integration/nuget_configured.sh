#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 - <<'SETUP'
import json
from pathlib import Path
Path('NuGet.Config').write_text('<configuration><packageSources><clear/><add key="nuget.org" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('<TargetFramework>net10.0</TargetFramework>','<TargetFrameworks>netstandard2.1;net10.0</TargetFrameworks><LangVersion>latest</LangVersion>').replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="$(PackageVersion)" Condition="\'$(RoundTrip)\' == \'a;b\'" /></ItemGroup></Project>'))
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'properties':{'PackageVersion':'12.0.3','RoundTrip':'a;b','RestoreUseStaticGraphEvaluation':'false'}},'entryProperties':{'App/App.csproj':{'PackageVersion':'13.0.3'},'Tests/Tests.csproj':{'PackageVersion':'13.0.3'}}}))
Path('BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")\nmsbuild_nuget_update(name="update_packages", projects=["App/App.csproj", "Tests/Tests.csproj"], mappings="mappings.json", framework="net10.0")\n')
SETUP
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'LOCKS'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text())
assert m['properties']['PackageVersion']=='12.0.3' and m['properties']['TargetFramework']=='net10.0'
assert {p['version'] for p in m['packages'] if p['id']=='Newtonsoft.Json'}=={'13.0.3'}
locks=json.loads(Path('Library/packages.lock.json').read_text())['dependencies']
assert set(locks)=={'.NETStandard,Version=v2.1','net10.0'},locks
assert all(v['Newtonsoft.Json']['resolved']=='13.0.3' for v in locks.values())
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nnuget=use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")\nnuget.lock(name="nuget", lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
p=Path('BUILD.bazel');p.write_text(p.read_text()+'\nload("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nmsbuild_sync(name="sync", projects=["App/App.csproj", "Tests/Tests.csproj"], mappings="mappings.json", framework="net10.0", package_lock="@nuget//:packages", package_build=True)\n')
LOCKS
bazel run //:sync
bazel run //:sync -- --check
cat >> BUILD.bazel <<'BZL'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
app_graph(name="graph")
msbuild_graph_test(name="test", graph=":graph", project="Tests/Tests.csproj")
BZL
bazel test //:test --remote_cache= --disk_cache= --test_output=errors
cp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cp Library/packages.lock.json "$TEST_TMPDIR/lock.before"
cp graph.generated.json "$TEST_TMPDIR/graph.before"
python3 - <<'CONFLICT'
import json
from pathlib import Path
p=Path('mappings.json');m=json.loads(p.read_text());m['entryProperties']['Tests/Tests.csproj']['PackageVersion']='12.0.3';p.write_text(json.dumps(m))
CONFLICT
if bazel run //:update_packages > "$TEST_TMPDIR/conflict.log" 2>&1; then echo 'Accepted conflicting shared project locks' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/conflict.log" 'Conflicting configured NuGet locks'
cmp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cmp Library/packages.lock.json "$TEST_TMPDIR/lock.before"
cmp graph.generated.json "$TEST_TMPDIR/graph.before"
python3 - <<'RESERVED'
import json
from pathlib import Path
p=Path('mappings.json');m=json.loads(p.read_text());m['entryProperties']['Tests/Tests.csproj']['RestoreLockedMode']='false';p.write_text(json.dumps(m))
RESERVED
if bazel run //:update_packages > "$TEST_TMPDIR/reserved.log" 2>&1; then echo 'Accepted a reserved Restore override' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/reserved.log" 'Reserved, ambiguous or conflicting'
cmp nuget.lock.json "$TEST_TMPDIR/manifest.before"
echo 'PASS: configured NuGet updates, all-framework locks, offline sync/test and conflict preservation'
