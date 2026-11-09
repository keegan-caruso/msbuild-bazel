#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
: "${QUALIFICATION_CACHE_URL:?Set an HTTP AC/CAS endpoint}"
# Separate this cold control from earlier runs using the same HTTP cache.
printf '<!-- Seed control: %s -->\n' "${scratch##*/}" >> Directory.Build.props
printf '{}\n' > mappings.json
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="sync",mappings="mappings.json",projects=["P2/P2.csproj"],srcs=glob(["P*/**","global.json","Directory.Build.*"]),package_build=True,resolve_references=True,qualification_cache=True,seed_build_cache=True)
BUILD
sync() {
    bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" "$@" > "$TEST_TMPDIR/$label.log" 2>&1 || { cat "$TEST_TMPDIR/$label.log" >&2; return 1; }
    assert_contains "$TEST_TMPDIR/$label.log" "GRAPH_CACHE_SEED {\"seeded\":$seeded,"
}
seeded=3
label=seed; sync
assert_contains "$TEST_TMPDIR/seed.log" '"hits":0,"misses":3,"uncacheable":0,"compilations":3'
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl","app_graph")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")
app_graph(name="graph",linux_stable_paths=True)
msbuild_graph_binary(name="app",graph=":graph",project="P2/P2.csproj")
BUILD
counts() {
    python3 - "$1" "$2" "$3" <<'PY'
import json,sys
from pathlib import Path
report=json.loads(Path('bazel-bin/graph.graph/report.json').read_text())
assert (report['hits'],report['misses'])==tuple(map(int,sys.argv[2:])),report
print('BUILD_SEED_CONTROL',sys.argv[1],json.dumps(report))
PY
}
run() {
    local options=()
    if [[ $1 != uncached ]]; then options+=(--action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL"); fi
    bazel run //:app --remote_cache= --disk_cache= "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; return 1; }
    [[ $(tail -1 "$TEST_TMPDIR/$1.log") == "$2" ]]
    counts "$1" "$3" "$4"
}
products() {
    # Ordinary project snapshots omit MSBuild's private AssemblyReference cache.
    (cd bazel-bin/graph.graph/workspace
     find P*/bin P*/obj/Release -type f ! -name "*.AssemblyReference.cache" -print0 | sort -z | xargs -0 sha256sum)
}
run first-build 1 3 0
products > "$TEST_TMPDIR/seeded.sha256"
# A separate source tree and output base have no producer project/action cache.
# Recover before running any ordinary compilation, so only qualification seeded it.
mkdir "$scratch/recovery"
python3 - "$scratch/recovery" <<'PY'
import shutil,sys
from pathlib import Path
for path in Path('.').iterdir():
    if path.name.startswith('bazel-'): continue
    target=Path(sys.argv[1])/path.name
    if path.is_dir(): shutil.copytree(path,target)
    else: shutil.copyfile(path,target)
PY
fresh_bazel() { "$BIT_BAZEL_BINARY" --nosystem_rc --nohome_rc --noworkspace_rc "--output_base=$scratch/recovery-bazel" "$@"; }
trap 'fresh_bazel shutdown >/dev/null 2>&1 || true; cleanup' EXIT
(
    cd "$scratch/recovery"
    fresh_bazel run //:app --repository_cache="$RULES_MSBUILD_TEST_REPOSITORY_CACHE" --remote_cache= --disk_cache= \
        --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/independent.log" 2>&1 || { cat "$TEST_TMPDIR/independent.log" >&2; exit 1; }
    [[ $(tail -1 "$TEST_TMPDIR/independent.log") == 1 ]]
    counts independent 3 0
    products > "$TEST_TMPDIR/independent.sha256"
    fresh_bazel shutdown
)
cmp "$TEST_TMPDIR/seeded.sha256" "$TEST_TMPDIR/independent.sha256"
run uncached 1 0 3
products > "$TEST_TMPDIR/uncached.sha256"
cmp "$TEST_TMPDIR/seeded.sha256" "$TEST_TMPDIR/uncached.sha256"
sed -i 's/=> 1;/=> 2;/' P0/Code.cs
run stale-seed-body 2 2 1
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
run stale-seed-api 2 1 2
cp graph.generated.json "$TEST_TMPDIR/contract.json"
cp graph.generated.bzl "$TEST_TMPDIR/contract.bzl"
printf 'invalid C#\n' > P0/Code.cs
if bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/rejected.log" 2>&1; then
    echo 'Failed compilation was accepted as a seed' >&2; exit 1
fi
cmp graph.generated.json "$TEST_TMPDIR/contract.json"
cmp graph.generated.bzl "$TEST_TMPDIR/contract.bzl"
if grep -Fq 'GRAPH_CACHE_SEED ' "$TEST_TMPDIR/rejected.log"; then
    echo 'Failed compilation published graph snapshots' >&2; exit 1
fi
printf 'public class P0 { public static int Value() => 1; }\n' > P0/Code.cs
# Replayed qualification snapshots must retain the complete bin/obj handoff.
label=qualification-replay; sync --action_env=RULES_MSBUILD_SYNC_PROFILE=1 -- --check
assert_contains "$TEST_TMPDIR/qualification-replay.log" '"hits":3,"misses":0,"uncacheable":0,"compilations":0'
run replayed-seed 1 3 0
products > "$TEST_TMPDIR/replayed.sha256"
cmp "$TEST_TMPDIR/seeded.sha256" "$TEST_TMPDIR/replayed.sha256"
# Build-generated files must stay absent during the pristine seed evaluation.
cat > Directory.Build.targets <<'GENERATED'
<Project><ItemGroup Condition="Exists('$(MSBuildProjectDirectory)/obj/post.marker')"><AdditionalFiles Include="$(MSBuildProjectDirectory)/obj/post.marker" /></ItemGroup><Target Name="GeneratedArtifact" AfterTargets="Build"><WriteLinesToFile File="$(MSBuildProjectDirectory)/obj/post.marker" Lines="generated artifact" Overwrite="true" /></Target></Project>
GENERATED
python3 - <<'GENERATED'
import hashlib,json
from pathlib import Path
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'referenceBoundary':True,'documents':{'Directory.Build.targets':{
    'sha256':hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),'targets':['GeneratedArtifact'],'tasks':[],'inputs':[]}}},
    'projects':{name+'/'+name+'.csproj':{'outputFiles':[name+'/obj/post.marker']} for name in ['P0','P1','P2']}}))
GENERATED
label=generated-artifact; sync
run generated-artifact 1 3 0
[[ $(cat bazel-bin/graph.graph/workspace/P0/obj/post.marker) == 'generated artifact' ]]
rm Directory.Build.targets
printf '{}\n' > mappings.json
# A different global configuration cannot consume the Release snapshots.
sed -i 's/seed_build_cache=True/seed_build_cache=True,configuration="Debug"/' BUILD.bazel
label=configuration; sync
assert_contains "$TEST_TMPDIR/configuration.log" '"hits":0,"misses":3,"uncacheable":0,"compilations":3'
run configuration 1 3 0
# Restore must not conceal an input mutation made by qualification targets.
cp graph.generated.json "$TEST_TMPDIR/before-mutation.json"
cp graph.generated.bzl "$TEST_TMPDIR/before-mutation.bzl"
cat > Directory.Build.targets <<'TARGETS'
<Project><Target Name="MutateRestoreInput" AfterTargets="Build" Condition="'$(MSBuildProjectName)' == 'P0'"><WriteLinesToFile File="$(MSBuildProjectExtensionsPath)/project.nuget.cache" Lines="changed after compilation" Overwrite="true" /></Target></Project>
TARGETS
python3 - <<'MAPPING'
import hashlib,json
from pathlib import Path
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'referenceBoundary':True,'documents':{'Directory.Build.targets':{
    'sha256':hashlib.sha256(Path('Directory.Build.targets').read_bytes()).hexdigest(),'targets':['MutateRestoreInput'],'tasks':[],'inputs':[]}}}}))
MAPPING
if bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/mutated.log" 2>&1; then
    echo 'Qualification input mutation was accepted' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/mutated.log" 'Qualification Build modified a seeded input:'
cmp graph.generated.json "$TEST_TMPDIR/before-mutation.json"
cmp graph.generated.bzl "$TEST_TMPDIR/before-mutation.bzl"
if grep -Fq 'GRAPH_CACHE_SEED ' "$TEST_TMPDIR/mutated.log"; then
    echo 'Input mutation published graph snapshots' >&2; exit 1
fi
rm Directory.Build.targets
printf '{}\n' > mappings.json
# Include an outer dispatcher and both inner frameworks in the next graph.
sed -i 's/seed_build_cache=True,configuration="Debug"/seed_build_cache=True/' BUILD.bazel
sed -i 's/projects=\["P2\/P2.csproj"\]/projects=["P2\/P2.csproj","P1\/P1.csproj"]/' BUILD.bazel
sed -i 's|<TargetFramework>net10.0</TargetFramework>|<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>|' P1/P1.csproj
seeded=4
label=multi-target; sync
assert_contains "$TEST_TMPDIR/multi-target.log" '"hits":1,"misses":3,"uncacheable":0,"compilations":3'
run multi-target 1 4 0
# A dependency-only multi-target project also has query nodes without Build.
sed -i 's/projects=\["P2\/P2.csproj","P1\/P1.csproj"\]/projects=["P2\/P2.csproj"]/' BUILD.bazel
seeded=4
label=consumer-only; sync
run consumer-only 1 4 0
# Model a non-assembly coordinator requested through Query, never Build.
mkdir PQuery
cat > PQuery/PQuery.csproj <<'QUERY'
<Project><Import Project="Sdk.props" Sdk="Microsoft.NET.Sdk" /><PropertyGroup><TargetFramework>net10.0</TargetFramework><UsingMicrosoftNoTargetsSdk>true</UsingMicrosoftNoTargetsSdk></PropertyGroup><Import Project="Sdk.targets" Sdk="Microsoft.NET.Sdk" /><Target Name="Build"><Error Text="The query coordinator must not receive Build" /></Target><Target Name="Query" /></Project>
QUERY
python3 - <<'QUERY'
import hashlib,json
from pathlib import Path
p=Path('P2/P2.csproj')
p.write_text(p.read_text().replace('</Project>','<ItemGroup><ProjectReference Include="../PQuery/PQuery.csproj" ReferenceOutputAssembly="false" Targets="Query" /></ItemGroup></Project>'))
Path('mappings.json').write_text(json.dumps({'projectDefaults':{'referenceBoundary':True,'documents':{'PQuery/PQuery.csproj':{
    'sha256':hashlib.sha256(Path('PQuery/PQuery.csproj').read_bytes()).hexdigest(),'targets':['Build','Query'],'tasks':[],'inputs':[]}}}}))
QUERY
label=query-coordinator; sync
run query-coordinator 1 4 0
grep -h '^GRAPH_CACHE_SEED ' "$TEST_TMPDIR/seed.log" "$TEST_TMPDIR/qualification-replay.log"
echo 'PASS: qualification seeds ordinary HTTP recovery; outputs match uncached Build; edits/configuration invalidate and failures cannot publish'
