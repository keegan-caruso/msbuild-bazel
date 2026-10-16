#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mkdir Other
cp P2/Code.cs Other/Code.cs
cat > Other/Other.csproj <<'PROJECT'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../P1/P1.csproj" /></ItemGroup></Project>
PROJECT
cat > Directory.Build.targets <<'TARGETS'
<Project>
  <Target Name="RestoreWalkProbe" BeforeTargets="_GenerateRestoreGraphProjectEntry">
    <Message Importance="high" Text="RESTORE_WALK: $(MSBuildProjectName)" />
  </Target>
  <Target Name="RestoreRootProbe" BeforeTargets="Restore">
    <Message Importance="high" Text="RESTORE_ROOT: $(MSBuildProjectName)" />
    <Error Condition="'$(FailRestore)' == 'true'" Text="Deliberate root failure" />
  </Target>
</Project>
TARGETS
python3 - <<'MAPPING'
import hashlib,json
from pathlib import Path
Path('mappings.json').write_text(json.dumps({'projectDefaults': {'referenceBoundary': True, 'preparedRestore': True,
    'documents': {'Directory.Build.targets': {'sha256': hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),
        'targets': ['RestoreWalkProbe', 'RestoreRootProbe'], 'tasks': [], 'inputs': []}}}}))
MAPPING
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="sync", projects=["P2/P2.csproj", "Other/Other.csproj"], mappings="mappings.json", package_build=True, resolve_references=True)
BUILD
bazel run //:sync > "$TEST_TMPDIR/preparation.log" 2>&1 || { cat "$TEST_TMPDIR/preparation.log" >&2; exit 1; }
for project in P0 P1; do [[ $(grep -c "RESTORE_WALK: $project$" "$TEST_TMPDIR/preparation.log") == 1 ]]; done
for project in P2 Other; do [[ $(grep -c "RESTORE_ROOT: $project$" "$TEST_TMPDIR/preparation.log") == 1 ]]; done
[[ ! -d P0/obj && ! -d Other/bin ]]
bazel run //:sync -- --check
cp graph.generated.json "$TEST_TMPDIR/graph.before"
cp graph.generated.bzl "$TEST_TMPDIR/build.before"
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
msbuild_graph_binary(name="other", graph=":graph", project="Other/Other.csproj")
BUILD
for app in app other; do
    bazel run "//:$app" --disk_cache= --remote_cache= > "$TEST_TMPDIR/$app.log" 2>&1 || { cat "$TEST_TMPDIR/$app.log" >&2; exit 1; }
    [[ $(tail -1 "$TEST_TMPDIR/$app.log") == 1 ]]
done
python3 - <<'FAILURE'
import json
from pathlib import Path
p=Path('mappings.json'); m=json.loads(p.read_text())
m['entryProperties']={'Other/Other.csproj': {'FailRestore': 'true'}}
p.write_text(json.dumps(m))
FAILURE
if bazel run //:sync > "$TEST_TMPDIR/failure.log" 2>&1; then echo 'Accepted failed root Restore' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failure.log" 'Deliberate root failure'
cmp graph.generated.json "$TEST_TMPDIR/graph.before"
cmp graph.generated.bzl "$TEST_TMPDIR/build.before"
echo 'PASS: shared Restore walk, authored root hooks, qualified builds and failure preservation'
