#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
python3 - <<'SETUP'
from pathlib import Path
Path('NuGet.Config').write_text('<configuration><packageSources><clear/><add key="root" value="https://api.nuget.org/v3/index.json"/><add key="disabled" value="https://example.invalid/v3/index.json"/></packageSources><disabledPackageSources><add key="disabled" value="true"/></disabledPackageSources><packageSourceMapping><clear/><packageSource key="root"><package pattern="*"/></packageSource></packageSourceMapping></configuration>')
Path('Library/NuGet.Config').write_text('<configuration><packageSources><clear/><add key="root" value="https://api.nuget.org/v3/index.json"/></packageSources><packageSourceMapping><clear/><packageSource key="root"><package pattern="Newtonsoft.Json"/></packageSource></packageSourceMapping></configuration>')
p=Path('Library/Library.csproj');p.write_text(p.read_text().replace('</Project>','<ItemGroup><PackageReference Include="Newtonsoft.Json" Version="13.0.3" /></ItemGroup></Project>'))
Path('BUILD.bazel').write_text('load("@rules_msbuild//msbuild:sync.bzl", "msbuild_nuget_update")\nmsbuild_nuget_update(name="update_packages", projects=["App/App.csproj", "Tests/Tests.csproj"])\n')
SETUP
bazel run //:update_packages
bazel run //:update_packages -- --check
python3 - <<'LOCKS'
import json
from pathlib import Path
m=json.loads(Path('nuget.lock.json').read_text());assert set(m['configDigests'])=={'NuGet.Config','Library/NuGet.Config'},m['configDigests']
assert any(p['id']=='Newtonsoft.Json' for p in m['packages'])
p=Path('MODULE.bazel');p.write_text(p.read_text()+'\nnuget=use_extension("@rules_msbuild//msbuild:nuget.bzl", "nuget")\nnuget.lock(name="nuget", lockfile="//:nuget.lock.json")\nuse_repo(nuget,"nuget")\n')
p=Path('BUILD.bazel');p.write_text(p.read_text()+'\nload("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nmsbuild_sync(name="sync", projects=["App/App.csproj", "Tests/Tests.csproj"], package_lock="@nuget//:packages", package_build=True)\n')
LOCKS
bazel run //:sync
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
cp Library/NuGet.Config "$TEST_TMPDIR/config.before"
# Each resolution gets an empty package cache: a mapping miss cannot hide behind it.
python3 - <<'MAPPING'
from pathlib import Path
p=Path('Library/NuGet.Config');p.write_text(p.read_text().replace('pattern="Newtonsoft.Json"','pattern="Unmatched.*"'))
MAPPING
if bazel run //:update_packages > "$TEST_TMPDIR/mapping.log" 2>&1; then echo 'Ignored nested package source mapping' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/mapping.log" 'NU1100'
cmp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cmp Library/packages.lock.json "$TEST_TMPDIR/lock.before"
cmp graph.generated.json "$TEST_TMPDIR/graph.before"
cp "$TEST_TMPDIR/config.before" Library/NuGet.Config
# Configuration-only changes are attested even when package bytes are identical.
echo '<!-- changed -->' >> Library/NuGet.Config
if bazel run //:update_packages -- --check > "$TEST_TMPDIR/config-check.log" 2>&1; then echo 'Accepted changed config digest' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/config-check.log" 'NuGet locks are stale'
cp "$TEST_TMPDIR/config.before" Library/NuGet.Config
# Authored RestoreConfigFile must not publish an ambient-config inventory.
cp NuGet.Config "$scratch/ambient.config"
printf '<Project><PropertyGroup><RestoreConfigFile>%s</RestoreConfigFile></PropertyGroup></Project>' "$scratch/ambient.config" > Directory.Build.props
if bazel run //:update_packages > "$TEST_TMPDIR/ambient.log" 2>&1; then echo 'Published ambient configuration' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/ambient.log" 'configuration outside the workspace'
cmp nuget.lock.json "$TEST_TMPDIR/manifest.before"
cmp Library/packages.lock.json "$TEST_TMPDIR/lock.before"
echo 'PASS: native nested NuGet hierarchy, source mappings, offline test, config attestation and failure preservation'
