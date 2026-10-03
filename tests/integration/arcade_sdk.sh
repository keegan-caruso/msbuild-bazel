#!/usr/bin/env bash
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
cp -R "$scratch/consumer" "$scratch/authored"
bazel build @dotnet//:files @packages//:archives > "$TEST_TMPDIR/bootstrap.log" 2>&1 || { cat "$TEST_TMPDIR/bootstrap.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
mkdir "$scratch/feed"
while read -r archive; do cp "$execroot/$archive" "$scratch/feed/"; done < <(bazel cquery @packages//:archives --output=files 2> "$TEST_TMPDIR/packages-query.log")
for mode in ordinary graph; do
    cp -R "$scratch/authored" "$scratch/raw-$mode"
    mkdir "$scratch/raw-$mode-scratch" "$scratch/raw-$mode/.package-source"
    cp "$scratch/feed/"* "$scratch/raw-$mode/.package-source/"
    cat > "$scratch/raw-$mode/NuGet.Config" <<'XML'
<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources></configuration>
XML
    graph=(); if [[ $mode == graph ]]; then graph=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-$mode" "$scratch/raw-$mode-scratch" msbuild App/App.csproj -restore -t:Build -m:4 "${graph[@]}" -p:Configuration=Release -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' > "$TEST_TMPDIR/raw-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$mode.log" >&2; exit 1; }
    (cd "$scratch/raw-$mode"; sha256sum artifacts/bin/App/Release/net10.0/App.dll artifacts/bin/Library/Release/net10.0/Library.dll) > "$TEST_TMPDIR/raw-$mode.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.sha256" "$TEST_TMPDIR/raw-graph.sha256"
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
app_graph(name="graph", linux_worker=True, linux_stable_paths=True)
msbuild_graph_binary(name="app", graph=":graph", project="App/App.csproj")
msbuild_graph_test(name="arcade_consumer", graph=":graph", project="App/App.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
build() {
    local start; start=$(python3 -c 'import time;print(time.monotonic())')
    bazel run //:app "${options[@]}" --build_event_json_file="$TEST_TMPDIR/$1.bep" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1.log" "ARCADE:$4:${5:-1.2.3-dev}"
    python3 - "$1" "$2" "$3" "$start" "$TEST_TMPDIR" <<'PY'
import json,sys,time
from pathlib import Path
row,hits,misses,start,logs=sys.argv[1:]
r=json.load(open('bazel-bin/graph.graph/report.json'));assert (r['hits'],r['misses'])==(int(hits),int(misses)),(row,r)
assert r['preparedRestore'];Path(logs,row+'-report.json').write_text(json.dumps(r))
with open(Path(logs,'timings.tsv'),'a') as f:f.write(f'{row}\t{time.monotonic()-float(start):.3f}\t{hits}\t{misses}\n')
PY
}
build seed 0 2 1
(cd bazel-bin/graph.graph/workspace; sha256sum artifacts/bin/App/Release/net10.0/App.dll artifacts/bin/Library/Release/net10.0/Library.dll) > "$TEST_TMPDIR/seed.sha256"
cmp "$TEST_TMPDIR/raw-graph.sha256" "$TEST_TMPDIR/seed.sha256"
python3 - "$scratch/raw-ordinary" "$scratch/raw-graph" bazel-bin/graph.graph/workspace <<'PYCOMPARE'
import sys,zipfile
from pathlib import Path
payloads=[]
for root in sys.argv[1:]:
 z=zipfile.ZipFile(Path(root,'artifacts/packages/Release/Shipping/Library.1.2.3-dev.nupkg'))
 payloads.append({n:z.read(n) for n in z.namelist() if n.endswith(('.dll','.pdb','.nuspec','.png'))})
assert payloads[0]==payloads[1]==payloads[2],'Pack payloads differ'
PYCOMPARE
build noop 0 2 1
sed -i 's/linux_worker=True,/linux_worker=True, profile_build=True,/' BUILD.bazel
build replay 2 0 1
sed -i 's/Value() => 1/Value() => 2/' Library/Code.cs
build body 1 1 2
printf 'public class Library { public static int Value() => 2; public static int Extra() => 3; }\n' > Library/Code.cs
build api 0 2 2
# A cold Pack must build first; GeneratePackageOnBuild instead assumes existing outputs.
python3 - <<'PYPACKPROPS'
import json
p='mappings.json';r=json.load(open(p));r['projectDefaults']['properties']={'GeneratePackageOnBuild':'false'};json.dump(r,open(p,'w'))
PYPACKPROPS
# Pack the packable library root. Pack on the nonpackable app does not build its dependencies.
sed -i 's/projects = \["App\/App.csproj"\]/projects = ["Library\/Library.csproj"]/' BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/pack-sync.log" 2>&1 || { cat "$TEST_TMPDIR/pack-sync.log" >&2; exit 1; }
sed -i 's/linux_worker=True,/linux_worker=True, target="Pack",/' BUILD.bazel
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/pack.log" 2>&1 || { cat "$TEST_TMPDIR/pack.log" >&2; exit 1; }
python3 - <<'PYPACK'
import json
r=json.load(open('bazel-bin/graph.graph/report.json'));assert (r['hits'],r['misses'])==(0,1),r
PYPACK
# Version metadata is an authored input, not ambient Git or today's date.
sed -i 's/<PatchVersion>3/<PatchVersion>4/' Directory.Build.props
sed -i 's/Library.1.2.3-dev/Library.1.2.4-dev/' mappings.json
bazel run //:sync > "$TEST_TMPDIR/version-sync.log" 2>&1 || { cat "$TEST_TMPDIR/version-sync.log" >&2; exit 1; }
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/version-pack.log" 2>&1 || { cat "$TEST_TMPDIR/version-pack.log" >&2; exit 1; }
[[ ! -f bazel-bin/graph.graph/workspace/artifacts/packages/Release/Shipping/Library.1.2.3-dev.nupkg ]]
[[ -f bazel-bin/graph.graph/workspace/artifacts/packages/Release/Shipping/Library.1.2.4-dev.nupkg ]]
python3 - <<'PYPACKPROPS'
import json
p='mappings.json';r=json.load(open(p));r['projectDefaults'].pop('properties');json.dump(r,open(p,'w'))
PYPACKPROPS
sed -i 's/projects = \["Library\/Library.csproj"\]/projects = ["App\/App.csproj"]/' BUILD.bazel
sed -i 's/target="Pack"/target="Build"/' BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/version-sync.log" 2>&1 || { cat "$TEST_TMPDIR/version-sync.log" >&2; exit 1; }
build version 0 2 2 1.2.4-dev
# Exercise Arcade's date-derived official versions with a declared build ID.
sed -i 's/<MajorVersion>/<OfficialBuild>true<\/OfficialBuild><OfficialBuildId>20261003.1<\/OfficialBuildId><MajorVersion>/' Directory.Build.props
sed -i 's/Library.1.2.4-dev.nupkg/Library.1.2.4-dev.26503.1.nupkg/' mappings.json
bazel run //:sync > "$TEST_TMPDIR/official-sync.log" 2>&1 || { cat "$TEST_TMPDIR/official-sync.log" >&2; exit 1; }
build official 0 2 2 1.2.4-dev.26503.1
cp -R "$scratch/authored" "$scratch/raw-official"
cp Directory.Build.props "$scratch/raw-official/"
cp Library/Code.cs "$scratch/raw-official/Library/"
mkdir "$scratch/raw-official-scratch" "$scratch/raw-official/.package-source"
cp "$scratch/feed/"* "$scratch/raw-official/.package-source/"
cp "$scratch/raw-ordinary/NuGet.Config" "$scratch/raw-official/"
bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-official" "$scratch/raw-official-scratch" msbuild App/App.csproj -restore -graphBuild -t:Build -p:Configuration=Release -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' > "$TEST_TMPDIR/raw-official.log" 2>&1 || { cat "$TEST_TMPDIR/raw-official.log" >&2; exit 1; }
for product in artifacts/bin/App/Release/net10.0/App.dll artifacts/bin/App/Release/net10.0/App.pdb artifacts/bin/Library/Release/net10.0/Library.dll; do
    cmp "$scratch/raw-official/$product" "bazel-bin/graph.graph/workspace/$product"
done
sed -i 's/<OfficialBuild>true<\/OfficialBuild><OfficialBuildId>20261003.1<\/OfficialBuildId>//' Directory.Build.props
sed -i 's/Library.1.2.4-dev.26503.1.nupkg/Library.1.2.4-dev.nupkg/' mappings.json
bazel run //:sync > "$TEST_TMPDIR/local-sync.log" 2>&1 || { cat "$TEST_TMPDIR/local-sync.log" >&2; exit 1; }
build local-version 0 2 2 1.2.4-dev
[[ ! -f bazel-bin/graph.graph/workspace/artifacts/packages/Release/Shipping/Library.1.2.4-dev.26503.1.nupkg ]]
sed -i 's/target="Build"/target="Publish"/' BUILD.bazel
build publish 0 2 2 1.2.4-dev
bazel test //:arcade_consumer "${options[@]}" --test_output=errors > "$TEST_TMPDIR/test.log" 2>&1 || { cat "$TEST_TMPDIR/test.log" >&2; exit 1; }
sed -i 's/profile_build=True/profile_build=True, worker_cache_mb=0/' BUILD.bazel
build uncached 0 2 2 1.2.4-dev
printf 'invalid C#\n' > Library/Code.cs
if bazel run //:app "${options[@]}" > "$TEST_TMPDIR/failure.log" 2>&1; then echo 'Invalid source succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failure.log" 'error CS'
cp "$scratch/authored/Library/Code.cs" Library/Code.cs
build recovery 0 2 1 1.2.4-dev
# Export the Arcade package as a Bazel product and consume it through a fresh graph.
cp graph.generated.json producer.generated.json
sed 's/graph.generated.json/producer.generated.json/g' graph.generated.bzl > producer.generated.bzl
sed -i 's/graph.generated.bzl/producer.generated.bzl/' BUILD.bazel
mkdir Consumer
cat > Consumer/Consumer.csproj <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><PackageReference Include="Library" Version="1.2.4-dev" /></ItemGroup></Project>
XML
printf 'System.Console.WriteLine("PACKAGE:" + Library.Value());\n' > Consumer/Program.cs
printf '{"projectDefaults":{"preparedRestore":true}}\n' > consumer-mappings.json
cat >> BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output", "msbuild_generated_nuget_package", "msbuild_package_lock")
msbuild_graph_output(name="library_package", graph=":graph", path="artifacts/packages/Release/Shipping/Library.1.2.4-dev.nupkg")
msbuild_generated_nuget_package(name="built_library", package_id="Library", version="1.2.4-dev", archive=":library_package")
msbuild_package_lock(name="built_lock", packages=[":built_library"])
msbuild_sync(name="package_sync", projects=["Consumer/Consumer.csproj"], package_lock=":built_lock", package_build=True, mappings="consumer-mappings.json")
BUILD
bazel run //:package_sync "${options[@]}" > "$TEST_TMPDIR/package-sync.log" 2>&1 || { cat "$TEST_TMPDIR/package-sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", package_graph="app_graph")
package_graph(name="package_consumer", linux_worker=True, linux_stable_paths=True)
msbuild_graph_binary(name="package_app", graph=":package_consumer", project="Consumer/Consumer.csproj")
msbuild_graph_test(name="package_test", graph=":package_consumer", project="Consumer/Consumer.csproj")
BUILD
bazel run //:package_app "${options[@]}" > "$TEST_TMPDIR/package-run.log" 2>&1 || { cat "$TEST_TMPDIR/package-run.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/package-run.log" 'PACKAGE:1'
bazel test //:package_test "${options[@]}" --test_output=errors > "$TEST_TMPDIR/package-test.log" 2>&1 || { cat "$TEST_TMPDIR/package-test.log" >&2; exit 1; }
for property in OfficialBuild DotNetUseShippingVersions; do
    python3 - "$property" <<'PYDATE'
import json,sys
p='mappings.json';r=json.load(open(p));r['projectDefaults']['properties']={sys.argv[1]:'true'};json.dump(r,open(p,'w'))
PYDATE
    if bazel run //:sync > "$TEST_TMPDIR/missing-build-id.log" 2>&1; then echo 'Ambient date-derived version succeeded' >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/missing-build-id.log" 'requires an explicit OfficialBuildId'
done
cat "$TEST_TMPDIR/timings.tsv"
echo 'PASS: composed Arcade SDK raw/Pack payload parity, explicit versioning, body/API edits, Publish, failure recovery and stale-product removal'
