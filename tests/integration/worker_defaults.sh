#!/usr/bin/env bash
# Worker defaults follow the qualified execution platform and retain explicit opt-outs.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync
printf '\nbazel_dep(name="platforms", version="1.0.0")\n' >> MODULE.bazel
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_restore")
platform(name="qualified", constraint_values=["@platforms//os:linux", "@platforms//cpu:aarch64", "@rules_msbuild//msbuild:qualified_linux_bwrap"])
app_graph(name="graph", profile_build=True)
app_graph(name="pack", target="Pack")
app_graph(name="publish", target="Publish")
app_graph(name="explicit_publish", target="Publish", linux_worker=True)
msbuild_graph_restore(name="restore_control", runner=":graph_runner", contract="graph.generated.json", srcs=glob(["P*/**", "global.json", "Directory.Build.*"]), linux_stable_paths=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
requirements() {
    local expected=$1 label=$2; shift 2
    local query
    printf -v query 'mnemonic("%s", //:%s)' "${ACTION_MNEMONIC:-MSBuildGraph}" "$label"
    bazel aquery "$query" --output=jsonproto "$@" > "$TEST_TMPDIR/action.json"
    python3 - "$TEST_TMPDIR/action.json" "$expected" <<'PY'
import json,sys
rows=json.load(open(sys.argv[1]))['actions'];assert len(rows)==1,rows
info={v['key']:v['value'] for v in rows[0].get('executionInfo',[])}
assert (info.get('supports-workers')=='1') == (sys.argv[2]=='worker'),info
PY
}
requirements portable graph
# A target-platform declaration cannot qualify the execution environment.
requirements portable graph --platforms=//:qualified
requirements worker graph --extra_execution_platforms=//:qualified
requirements portable pack --extra_execution_platforms=//:qualified
requirements portable publish --extra_execution_platforms=//:qualified
requirements worker explicit_publish --extra_execution_platforms=//:qualified
ACTION_MNEMONIC=MSBuildGraphRestore requirements portable restore_control --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified --execution_log_json_file="$TEST_TMPDIR/default-execution.json" > "$TEST_TMPDIR/default.log" 2>&1 || { cat "$TEST_TMPDIR/default.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/default.log") == 1 ]]
python3 - "$TEST_TMPDIR/default-execution.json" <<'PY'
import json,sys
text=open(sys.argv[1]).read();decoder=json.JSONDecoder();rows=[]
while text.strip():
 row,used=decoder.raw_decode(text.lstrip());rows.append(row);text=text.lstrip()[used:]
assert any(r.get('mnemonic')=='MSBuildGraph' and r.get('runner')=='worker' for r in rows),rows
assert 'worker' in json.load(open('bazel-bin/graph.graph/report.json'))
PY
# Keep automatic selection while editing one implementation. The persistent
# worker must reuse the two unaffected projects, without an HTTP cache backend.
sed -i 's/=> 1/=> 2/' P0/Code.cs
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/body.log" 2>&1 || { cat "$TEST_TMPDIR/body.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/body.log") == 2 ]]
python3 - <<'PY_BODY'
import json
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert 'worker' in r and (r['hits'],r['misses'])==(2,1),r
PY_BODY
sed -i 's/=> 2/=> 1/' P0/Code.cs
sed -i 's/app_graph(name="graph", profile_build=True)/app_graph(name="graph", profile_build=True, linux_worker=False)/' BUILD.bazel
requirements portable graph --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/disabled.log" 2>&1 || { cat "$TEST_TMPDIR/disabled.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/disabled.log") == 1 ]]
python3 - <<'PY'
import json
assert 'worker' not in json.load(open('bazel-bin/graph.graph/report.json'))
PY
sed -i 's/profile_build=True, linux_worker=False/profile_build=True, linux_stable_paths=False/' BUILD.bazel
requirements portable graph --extra_execution_platforms=//:qualified
bazel run //:app --extra_execution_platforms=//:qualified > "$TEST_TMPDIR/portable.log" 2>&1 || { cat "$TEST_TMPDIR/portable.log"; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/portable.log") == 1 ]]
echo 'PASS: qualified execution defaults to actual Bazel workers; target-only, explicit worker False and portable stable-path overrides remain non-worker'
