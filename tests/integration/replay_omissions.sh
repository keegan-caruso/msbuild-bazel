#!/usr/bin/env bash
# Reviewed optional intermediates stay in complete snapshots, not build products.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
printf '{}\n' > mappings.json
sed 's/projects = \["P2\/P2.csproj"\]/projects = ["P2\/P2.csproj"], mappings="mappings.json"/' BUILD.bazel.in > BUILD.bazel
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_worker=True, linux_stable_paths=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
run() {
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
    cp bazel-bin/graph.graph/report.json "$TEST_TMPDIR/$1-report.json"
}
products() {
    (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj/Release/net10.0/ref -type f ! -name '*.AssemblyReference.cache' -print0 | sort -z | xargs -0 sha256sum)
}
run baseline 1
products > "$TEST_TMPDIR/baseline.sha256"
sed -i 's/profile_build=True/profile_build=False/' BUILD.bazel
run baseline-replay 1
sed -i 's/profile_build=False/profile_build=True/' BUILD.bazel
run baseline-profile 1
cat > mappings.json <<'JSON'
{"projectDefaults":{"replayOmissions":["$(IntermediateOutputPath)$(TargetFileName)","$(IntermediateOutputPath)$(TargetName).pdb"]}}
JSON
bazel run //:sync > "$TEST_TMPDIR/omissions-sync.log" 2>&1 || { cat "$TEST_TMPDIR/omissions-sync.log" >&2; exit 1; }
run omitted-seed 1
for i in 0 1 2; do
    [[ ! -e bazel-bin/graph.graph/workspace/P$i/obj/Release/net10.0/P$i.dll ]]
    [[ ! -e bazel-bin/graph.graph/workspace/P$i/obj/Release/net10.0/P$i.pdb ]]
done
products > "$TEST_TMPDIR/omitted.sha256"
cmp "$TEST_TMPDIR/baseline.sha256" "$TEST_TMPDIR/omitted.sha256"
sed -i 's/profile_build=True/profile_build=False/' BUILD.bazel
run omitted-replay 1
sed -i 's/profile_build=False/profile_build=True/' BUILD.bazel
run omitted-profile 1
products > "$TEST_TMPDIR/recovered.sha256"
cmp "$TEST_TMPDIR/baseline.sha256" "$TEST_TMPDIR/recovered.sha256"
python3 - "$TEST_TMPDIR" <<'PY'
import json,sys
from pathlib import Path
logs=Path(sys.argv[1]);base=json.load(open(logs/'baseline-profile-report.json'));small=json.load(open(logs/'omitted-profile-report.json'))
assert (base['hits'],base['misses'])==(3,0),base
assert (small['hits'],small['misses'])==(3,0),small
assert small['operations']['omittedReplay']['calls']==6,small
assert small['materialization']['bytes']<base['materialization']['bytes'],(base,small)
print('PASS: replayed bytes',base['materialization']['bytes'],'->',small['materialization']['bytes'],';',small['operations']['omittedReplay']['calls'],'copies omitted')
PY
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run body 2
python3 - "$TEST_TMPDIR/body-report.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));assert (r["hits"],r["misses"])==(2,1),r
PY
printf 'public class P0 { public static int Value() => 2; public static int Extra() => 3; }\n' > P0/Code.cs
run api 2
python3 - "$TEST_TMPDIR/api-report.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]));assert (r["hits"],r["misses"])==(1,2),r
PY
products > "$TEST_TMPDIR/edited.sha256"
bazel shutdown
bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run uncached-control 2
products > "$TEST_TMPDIR/control.sha256"
cmp "$TEST_TMPDIR/edited.sha256" "$TEST_TMPDIR/control.sha256"
# Ownership and required products cannot be waived by an omission contract.
for omission in '$(TargetPath)' '$(IntermediateOutputPath)ref/$(TargetFileName)' '../P1/bin/Release/net10.0/P1.dll'; do
    python3 - "$omission" <<'PY'
import json,sys
json.dump({'projects':{'P0/P0.csproj':{'replayOmissions':[sys.argv[1]]}}},open('mappings.json','w'))
PY
    bazel run //:sync > "$TEST_TMPDIR/reject-sync.log" 2>&1 || { cat "$TEST_TMPDIR/reject-sync.log" >&2; exit 1; }
    if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/reject.log" 2>&1; then echo 'Invalid replay omission succeeded' >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/reject.log" 'Replay omission must be an optional owned file'
done
echo 'PASS: optional intermediate omissions preserve app/reference bytes, edits and uncached parity; required/foreign products rejected'
