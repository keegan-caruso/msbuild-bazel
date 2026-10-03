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
    graph=(); if [[ $mode == graph ]]; then graph=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/raw-$mode" "$scratch/raw-$mode-scratch" msbuild App/App.csproj -restore -t:Build -m:4 "${graph[@]}" -p:Configuration=Release -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' > "$TEST_TMPDIR/raw-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/raw-$mode.log" >&2; exit 1; }
    (cd "$scratch/raw-$mode"; sha256sum App/bin/Release/net10.0/App.{dll,pdb} Library/bin/Release/net10.0/Library.{dll,pdb} App/bin/Release/net10.0/appsettings.json) > "$TEST_TMPDIR/raw-$mode.sha256"
done
cmp "$TEST_TMPDIR/raw-ordinary.sha256" "$TEST_TMPDIR/raw-graph.sha256"
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
app_graph(name="graph", linux_worker=True, linux_stable_paths=True)
msbuild_graph_binary(name="app", graph=":graph", project="App/App.csproj")
msbuild_graph_test(name="bounded_worker", graph=":graph", project="App/App.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
build() {
    local start; start=$(python3 -c 'import time;print(time.monotonic())')
    bazel run //:app "${options[@]}" --build_event_json_file="$TEST_TMPDIR/$1.bep" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1.log" "WORKER:$4:$5"
    python3 - "$1" "$2" "$3" "$start" "$TEST_TMPDIR" <<'PY'
import json,sys,time
from pathlib import Path
row,hits,misses,start,logs=sys.argv[1:]
r=json.load(open('bazel-bin/graph.graph/report.json')); assert (r['hits'],r['misses'])==(int(hits),int(misses)),(row,r)
assert r['preparedRestore']
Path(logs,row+'-report.json').write_text(json.dumps(r))
with open(Path(logs,'timings.tsv'),'a') as f:f.write(f'{row}\t{time.monotonic()-float(start):.3f}\t{hits}\t{misses}\n')
PY
}
build seed 0 2 1 42
(cd bazel-bin/graph.graph/workspace; sha256sum App/bin/Release/net10.0/App.{dll,pdb} Library/bin/Release/net10.0/Library.{dll,pdb} App/bin/Release/net10.0/appsettings.json) > "$TEST_TMPDIR/seed.sha256"
cmp "$TEST_TMPDIR/raw-graph.sha256" "$TEST_TMPDIR/seed.sha256"
build noop 0 2 1 42
python3 - "$TEST_TMPDIR/noop.bep" <<'PY'
import json,sys
m=next(json.loads(l)['buildMetrics'] for l in open(sys.argv[1]) if 'buildMetrics' in json.loads(l))
assert not any(int(a.get('actionsExecuted',0)) for a in m['actionSummary'].get('actionData',[]) if a['mnemonic'] in ['MSBuildGraph','MSBuildGraphRestore'])
PY
sed -i 's/linux_worker=True,/linux_worker=True, profile_build=True,/' BUILD.bazel
build replay 2 0 1 42
sed -i 's/Value() => 1/Value() => 2/' Library/Code.cs
build body 1 1 2 42
printf 'public class Library { public static int Value() => 2; public static int Extra() => 3; }\n' > Library/Code.cs
build api 0 2 2 42
sed -i 's/42/43/' App/appsettings.json
build config 1 1 2 43
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from pathlib import Path
for row in ['body','api','config']:
 m=next(json.loads(l)['buildMetrics'] for l in open(Path(sys.argv[1],row+'.bep')) if 'buildMetrics' in json.loads(l))
 assert not any(int(a.get('actionsExecuted',0)) for a in m['actionSummary'].get('actionData',[]) if a['mnemonic']=='MSBuildGraphRestore'),row
PY
# SDK elements use the same MSBuild imports and product model as the root attribute.
sed -i 's/<Project Sdk="Microsoft.NET.Sdk.Worker">/<Project><Sdk Name="Microsoft.NET.Sdk.Worker" \/>/' App/App.csproj
bazel run //:sync > "$TEST_TMPDIR/element-sync.log" 2>&1 || { cat "$TEST_TMPDIR/element-sync.log" >&2; exit 1; }
build sdk-element 0 2 2 43
sed -i 's/linux_worker=True,/linux_worker=True, target="Publish",/' BUILD.bazel
build publish 0 2 2 43
[[ -f bazel-bin/graph.graph/workspace/App/bin/Release/net10.0/publish/appsettings.json ]]
bazel test //:bounded_worker "${options[@]}" --test_output=errors > "$TEST_TMPDIR/test.log" 2>&1 || { cat "$TEST_TMPDIR/test.log" >&2; exit 1; }
sed -i 's/profile_build=True/profile_build=True, worker_cache_mb=0/' BUILD.bazel
build uncached 0 2 2 43
printf 'invalid C#\n' > Library/Code.cs
if bazel run //:app "${options[@]}" > "$TEST_TMPDIR/failure.log" 2>&1; then echo 'Invalid source succeeded' >&2; exit 1; fi
assert_contains "$TEST_TMPDIR/failure.log" 'error CS'
printf 'public class Library { public static int Value() => 3; }\n' > Library/Code.cs
build recovery 0 2 3 43
cat "$TEST_TMPDIR/timings.tsv"
echo 'PASS: Worker SDK raw parity, root/element sync, body/API/config edits, Publish, bounded execution and failure recovery'
# Generate the official template from the verified SDK; keep its project/source unchanged.
"$sdk/dotnet" new worker --name UpstreamWorker --output UpstreamWorker --framework net10.0 --no-restore > "$TEST_TMPDIR/template.log"
mkdir "$scratch/template-source"
cp -R UpstreamWorker "$scratch/template-source/"
cp Directory.Build.props "$scratch/template-source/"
for mode in ordinary graph; do
    cp -R "$scratch/template-source" "$scratch/template-$mode"
    mkdir "$scratch/template-$mode-scratch" "$scratch/template-$mode/.package-source"
    cp "$scratch/feed/"* "$scratch/template-$mode/.package-source/"
    graph=(); if [[ $mode == graph ]]; then graph=(-graphBuild); fi
    bash "$runner_dir/raw_namespace.sh" "$sdk" "$scratch/template-$mode" "$scratch/template-$mode-scratch" msbuild UpstreamWorker/UpstreamWorker.csproj -restore "${graph[@]}" -t:Build -p:Configuration=Release -p:UseSharedCompilation=false -p:PathMap='/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk' > "$TEST_TMPDIR/template-$mode.log" 2>&1 || { cat "$TEST_TMPDIR/template-$mode.log" >&2; exit 1; }
done
sed -i 's/projects = \["App\/App.csproj"\]/projects = ["UpstreamWorker\/UpstreamWorker.csproj"]/' BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/template-sync.log" 2>&1 || { cat "$TEST_TMPDIR/template-sync.log" >&2; exit 1; }
bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/template-build.log" 2>&1 || { cat "$TEST_TMPDIR/template-build.log" >&2; exit 1; }
for ext in dll pdb; do
    cmp "$scratch/template-ordinary/UpstreamWorker/bin/Release/net10.0/UpstreamWorker.$ext" "$scratch/template-graph/UpstreamWorker/bin/Release/net10.0/UpstreamWorker.$ext"
    cmp "$scratch/template-graph/UpstreamWorker/bin/Release/net10.0/UpstreamWorker.$ext" "bazel-bin/graph.graph/workspace/UpstreamWorker/bin/Release/net10.0/UpstreamWorker.$ext"
done
cmp UpstreamWorker/UpstreamWorker.csproj "$scratch/template-source/UpstreamWorker/UpstreamWorker.csproj"
cat >> BUILD.bazel <<'BUILD'
msbuild_graph_binary(name="upstream_app", graph=":graph", project="UpstreamWorker/UpstreamWorker.csproj")
BUILD
bazel build //:upstream_app "${options[@]}" > "$TEST_TMPDIR/template-launcher.log" 2>&1 || { cat "$TEST_TMPDIR/template-launcher.log" >&2; exit 1; }
if env -u RUNFILES_DIR -u RUNFILES_MANIFEST_FILE -u TEST_SRCDIR timeout --preserve-status --signal=INT 3s bazel-bin/upstream_app > "$TEST_TMPDIR/template-run.log" 2>&1; then
    :
else
    status=$?
    [[ $status == 130 ]] || { cat "$TEST_TMPDIR/template-run.log" >&2; exit "$status"; }
fi
assert_contains "$TEST_TMPDIR/template-run.log" 'Worker running at:'
assert_contains "$TEST_TMPDIR/template-run.log" 'Application is shutting down...'
printf 'PASS: unchanged official Worker template raw parity, public sync and bounded execution\n'
