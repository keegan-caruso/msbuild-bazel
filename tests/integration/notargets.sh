#!/usr/bin/env bash
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
cp -R "$scratch/consumer" "$scratch/authored"
bazel build @dotnet//:files @traversal_sdk//file @notargets_sdk//file > "$TEST_TMPDIR/bootstrap.log" 2>&1 || { cat "$TEST_TMPDIR/bootstrap.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
mkdir "$scratch/feed"
for label in traversal_sdk notargets_sdk; do
    archive=$(realpath "$execroot/$(bazel cquery "@$label//file" --output=files 2> "$TEST_TMPDIR/$label-query.log")")
    cp "$archive" "$scratch/feed/"
done
# Ordinary and graph MSBuild use the same source and SDK namespace as the action.
for mode in ordinary graph; do
    cp -R "$scratch/authored" "$scratch/raw-$mode"
    mkdir "$scratch/raw-$mode-scratch" "$scratch/raw-$mode/.package-source"
    cp "$scratch/feed/"* "$scratch/raw-$mode/.package-source/"
    printf '<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources></configuration>\n' > "$scratch/raw-$mode/NuGet.Config"
    graph_option=(); if [[ $mode == graph ]]; then graph_option=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-$mode" "$scratch/raw-$mode-scratch" \
        msbuild dirs.proj -restore -t:Build -m:4 "${graph_option[@]}" -p:Configuration=Release \
        -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' \
        > "$TEST_TMPDIR/raw-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$mode.log" >&2; exit 1; }
    (cd "$scratch/raw-$mode"; sha256sum Utility/out/proof.txt Library/bin/Release/net10.0/Library.{dll,pdb} Consumer/bin/Release/net10.0/Consumer.{dll,pdb} Consumer/bin/Release/net10.0/proof.txt) > "$TEST_TMPDIR/raw-$mode.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.sha256" "$TEST_TMPDIR/raw-graph.sha256"
sync_graph() {
    bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }
    bazel run //:sync -- --check > "$TEST_TMPDIR/$1-check.log" 2>&1 || { cat "$TEST_TMPDIR/$1-check.log" >&2; exit 1; }
}
sync_graph seed
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_output")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_output(name="proof", graph=":graph", path="Utility/out/proof.txt")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
report=bazel-bin/graph.graph/report.json
build() {
    bazel build //:proof "${options[@]}" --build_event_json_file="$TEST_TMPDIR/$1.bep" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    python3 - "$report" "$2" "$3" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));assert (r['hits'],r['misses'])==(int(sys.argv[2]),int(sys.argv[3])),r
assert r['preparedRestore']
PY
    [[ "$(head -1 bazel-bin/graph.graph/workspace/Utility/out/proof.txt)" == "$4" ]]
    cp "$report" "$TEST_TMPDIR/$1-report.json"
}
build seed 0 3 42
(cd bazel-bin/graph.graph/workspace; sha256sum Utility/out/proof.txt Library/bin/Release/net10.0/Library.{dll,pdb} Consumer/bin/Release/net10.0/Consumer.{dll,pdb} Consumer/bin/Release/net10.0/proof.txt) > "$TEST_TMPDIR/seed.sha256"
cmp "$TEST_TMPDIR/raw-graph.sha256" "$TEST_TMPDIR/seed.sha256"
python3 - <<'PY'
import json
c=json.load(open('graph.generated.json'))
assert len(c['Projects'])==5
for p in ['Utility/Utility.proj','Empty/Empty.csproj']:
    row=c['Projects'][p]['Configurations'][0]
    assert row['OutputDirectories']==[] and not row['ReferenceBoundary'],row
assert c['Projects']['Utility/Utility.proj']['Configurations'][0]['OutputFiles']==['Utility/out/proof.txt']
assert c['Projects']['Empty/Empty.csproj']['Configurations'][0]['OutputFiles']==[]
text=open('graph.generated.bzl').read()
assert 'Utility.proj|net10.0' not in text and 'Empty.csproj|net10.0' not in text
assert 'Utility/obj/project.assets.json' in c['Restore']['Outputs']
PY
[[ ! -e bazel-bin/graph.graph/workspace/Utility/bin && ! -e bazel-bin/graph.graph/workspace/Empty/bin && ! -e bazel-bin/graph.graph/workspace/Utility/input.txt ]]
# Force another graph action to prove both assembly and non-assembly snapshots replay.
sed -i 's/linux_worker=True)/linux_worker=True, profile_build=True)/' BUILD.bazel
build replay 3 0 42
cmp bazel-bin/graph.graph/workspace/Utility/out/proof.txt bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt
# Change only the declared text input: Library hits, utility regenerates, Restore reuses.
printf '43\n' > Utility/input.txt
build input-edit 1 2 43
cmp bazel-bin/graph.graph/workspace/Utility/out/proof.txt bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt
python3 - "$TEST_TMPDIR/input-edit.bep" <<'PY'
import json,sys
m=next(json.loads(l)['buildMetrics'] for l in open(sys.argv[1]) if 'buildMetrics' in json.loads(l))
assert not any(int(a.get('actionsExecuted',0)) for a in m['actionSummary'].get('actionData',[]) if a['mnemonic']=='MSBuildGraphRestore')
PY
# Source edits invalidate the managed dependency and the utility's conservative key.
printf 'public class Library { public static int Value() => 2; }\n' > Library/Code.cs
cp bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt "$TEST_TMPDIR/before-dependency.txt"
build dependency-edit 0 3 43
cmp bazel-bin/graph.graph/workspace/Utility/out/proof.txt bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt
if cmp -s "$TEST_TMPDIR/before-dependency.txt" bazel-bin/graph.graph/workspace/Consumer/bin/Release/net10.0/proof.txt; then echo "Stale dependency product" >&2; exit 1; fi
# Public sync also accepts a NoTargets .proj as the graph entry.
# Changing graph scope changes the prepared Restore contract and snapshot keys.
sed -i 's/projects = \["dirs.proj"\]/projects = ["Utility\/Utility.proj"]/' BUILD.bazel
sync_graph direct-entry
build direct-entry 0 2 43
# Empty NoTargets projects have no products and remain uncached.
sed -i 's/projects = \["Utility\/Utility.proj"\]/projects = ["Empty\/Empty.csproj"]/' BUILD.bazel
sync_graph empty-entry
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/empty.log" 2>&1 || { cat "$TEST_TMPDIR/empty.log" >&2; exit 1; }
assert_contains "$report" '"hits":0'
assert_contains "$report" '"misses":0'
# Restore the utility graph for rejection/ownership controls.
sed -i 's/projects = \["Empty\/Empty.csproj"\]/projects = ["Utility\/Utility.proj"]/' BUILD.bazel
sync_graph restore-entry
cp mappings.json "$scratch/mappings.json"
reject_sync() {
    if bazel run //:sync > "$TEST_TMPDIR/$1.log" 2>&1; then echo "Unexpected sync success: $1" >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/$1.log" "$2"
}
python3 - <<'PY'
import json
p='mappings.json';m=json.load(open(p));del m['projects']['Utility/Utility.proj']['documents'];open(p,'w').write(json.dumps(m))
PY
reject_sync missing-document 'custom targets/tasks require reviewed documents'
cp "$scratch/mappings.json" mappings.json
python3 - <<'PY'
import json
p='mappings.json';m=json.load(open(p));m['projects']['Utility/Utility.proj']['compilerReference']='Utility/out/proof.txt';open(p,'w').write(json.dumps(m))
PY
reject_sync compiler-reference 'configured managed DLL producer'
cp "$scratch/mappings.json" mappings.json
sed -i 's/3.7.0/99.0.0/' global.json
reject_sync missing-sdk 'Microsoft.Build.NoTargets'
sed -i 's/99.0.0/3.7.0/' global.json
python3 - <<'PY'
import json
p='mappings.json';m=json.load(open(p));m['projects']['Utility/Utility.proj']['outputFiles']=['Utility/out/missing.txt'];open(p,'w').write(json.dumps(m))
PY
sync_graph missing-product
if bazel build //:proof "${options[@]}" > "$TEST_TMPDIR/missing-product.log" 2>&1; then echo 'Unexpected missing product success' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/missing-product.log" 'Missing declared output file'
cp "$scratch/mappings.json" mappings.json
sync_graph restored
# An uncached worker regenerates the same utility products.
sed -i 's/profile_build=True/profile_build=True, worker_cache_mb=0/' BUILD.bazel
build uncached 0 2 43
echo 'PASS: NoTargets sync, explicit products, raw parity, replay, input/dependency edits, empty roots and rejection controls'
