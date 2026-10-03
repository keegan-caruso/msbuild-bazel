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
    (cd "$scratch/raw-$mode"; sha256sum App/bin/Release/net10.0/App.{dll,pdb} Library/bin/Release/net10.0/Library.dll) > "$TEST_TMPDIR/raw-$mode.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.sha256" "$TEST_TMPDIR/raw-graph.sha256"
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
app_graph(name="graph", linux_worker=True, linux_stable_paths=True)
msbuild_graph_binary(name="app", graph=":graph", project="App/App.csproj")
msbuild_graph_test(name="il_consumer", graph=":graph", project="App/App.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
build() {
    local start; start=$(python3 -c 'import time;print(time.monotonic())')
    bazel run //:app "${options[@]}" --build_event_json_file="$TEST_TMPDIR/$1.bep" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1.log" "IL:$4"
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
(cd bazel-bin/graph.graph/workspace; sha256sum App/bin/Release/net10.0/App.{dll,pdb} Library/bin/Release/net10.0/Library.dll) > "$TEST_TMPDIR/seed.sha256"
cmp "$TEST_TMPDIR/raw-graph.sha256" "$TEST_TMPDIR/seed.sha256"
[[ ! -f bazel-bin/graph.graph/workspace/Library/obj/Release/net10.0/ref/Library.dll ]]
build noop 0 2 1
sed -i 's/linux_worker=True,/linux_worker=True, profile_build=True,/' BUILD.bazel
build replay 2 0 1
sed -i 's/ldc.i4.1/ldc.i4.2/' Library/Code.il
build body 0 2 2
sed -i 's/.maxstack 1/.maxstack 2/' Library/Code.il
build stack 0 2 2
sed -i 's/^}/  .method public static int32 Extra() cil managed { .maxstack 1 ldc.i4.3 ret }\n}/' Library/Code.il
build api 0 2 2
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from pathlib import Path
for row in ['body','stack','api']:
 m=next(json.loads(l)['buildMetrics'] for l in open(Path(sys.argv[1],row+'.bep')) if 'buildMetrics' in json.loads(l))
 assert not any(int(a.get('actionsExecuted',0)) for a in m['actionSummary'].get('actionData',[]) if a['mnemonic']=='MSBuildGraphRestore'),row
PY
sed -i 's/linux_worker=True,/linux_worker=True, target="Publish",/' BUILD.bazel
build publish 0 2 2
bazel test //:il_consumer "${options[@]}" --test_output=errors > "$TEST_TMPDIR/test.log" 2>&1 || { cat "$TEST_TMPDIR/test.log" >&2; exit 1; }
sed -i 's/profile_build=True/profile_build=True, worker_cache_mb=0/' BUILD.bazel
build uncached 0 2 2
printf 'invalid IL\n' > Library/Code.il
if bazel run //:app "${options[@]}" > "$TEST_TMPDIR/failure.log" 2>&1; then echo 'Invalid IL succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failure.log" 'error'
cp "$scratch/authored/Library/Code.il" Library/Code.il
build recovery 0 2 1
# The tool packages are mandatory even though the SDK itself is present.
python3 - <<'PY'
import json
p='packages.json';r=json.load(open(p));json.dump([x for x in r if not x['id'].lower().endswith('.ilasm')],open(p,'w'))
PY
if bazel run //:sync > "$TEST_TMPDIR/missing-tool.log" 2>&1; then echo 'Missing ILAsm package succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/missing-tool.log" 'runtime.linux-arm64.microsoft.netcore.ilasm'
cp "$scratch/authored/packages.json" packages.json
sed -i 's/projects = \["App\/App.csproj"\]/projects = ["Library\/Library.ilproj"]/' BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/il-root-sync.log" 2>&1 || { cat "$TEST_TMPDIR/il-root-sync.log" >&2; exit 1; }
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/il-root-build.log" 2>&1 || { cat "$TEST_TMPDIR/il-root-build.log" >&2; exit 1; }
python3 - <<'PYROOT'
import json
r=json.load(open('bazel-bin/graph.graph/report.json'));assert (r['hits'],r['misses'])==(0,1),r
assert list(json.load(open('graph.generated.json'))['Projects'])==['Library/Library.ilproj']
PYROOT
cat "$TEST_TMPDIR/timings.tsv"
echo 'PASS: IL SDK deterministic raw parity, real managed consumer, implementation invalidation, Publish and missing-tool/failure recovery'
