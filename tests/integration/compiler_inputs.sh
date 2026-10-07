#!/usr/bin/env bash
# Complete SDK compiler selections narrow invalidation without pruning execution.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
# Keep P0 in MSBuild's execution/copy graph, but exclude it from P2's compiler.
sed -i 's|</Project>|<Target Name="DropUnusedCompilerReference" BeforeTargets="FindReferenceAssembliesForReferences"><ItemGroup><ReferencePath Remove="@(ReferencePath)" Condition="\x27%(Filename)\x27 == \x27P0\x27" /></ItemGroup></Target></Project>|' P2/P2.csproj
mapping() {
    python3 - "$1" <<'PY'
import hashlib,json,sys
from pathlib import Path
mode=sys.argv[1]
def binding(refs):
    return dict(referenceBoundary=True,compilerReferencesComplete=True,compilerReferences={p+'/'+p+'.csproj':p+'/obj/$(Configuration)/net10.0/ref/'+p+'.dll' for p in refs})
p2=binding(['P1'] if mode!='transitive' else ['P0','P1'])
if mode!='transitive':
    p2['documents']={'P2/P2.csproj':dict(sha256=hashlib.sha256(Path('P2/P2.csproj').read_bytes()).hexdigest(),targets=['DropUnusedCompilerReference'],tasks=[],inputs=[])}
if mode=='missing': p2['compilerReferences']={}
if mode=='unused': p2['compilerReferences']['P0/P0.csproj']='P0/obj/$(Configuration)/net10.0/ref/P0.dll'
if mode=='tool': p2['implementationDependencies']=['P1/P1.csproj']
Path('compiler.json').write_text(json.dumps(dict(projects={'P0/P0.csproj':binding([]),'P1/P1.csproj':binding(['P0']),'P2/P2.csproj':p2})))
PY
}
mapping narrow
sed -i 's/projects = \["P2\/P2.csproj"\]/projects = ["P2\/P2.csproj"], mappings = "compiler.json"/' BUILD.bazel
sync() { bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }; }
sync seed
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() { bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }; [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == 1 ]]; }
counts() {
    python3 - "$1" "$2" <<'PY'
import json,sys
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==(int(sys.argv[1]),int(sys.argv[2])),r
PY
}
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
run seed; counts 0 3
printf 'public class P0 { public static int Value() => 1; public static int Added() => 2; }\n' > P0/Code.cs
run api; counts 1 2
products > "$TEST_TMPDIR/api.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh; counts 0 3
products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/fresh.sha256"
# Incomplete/stale inventories must fail before storing a new snapshot.
for mode in missing unused; do
    mapping "$mode"; sync "$mode"
    if bazel build //:graph "${options[@]}" > "$TEST_TMPDIR/$mode.log" 2>&1; then echo "Accepted $mode compiler inventory" >&2; exit 1; fi
    assert_contains "$TEST_TMPDIR/$mode.log" 'Complete compiler references differ from SDK selection'
done
mapping tool; sync tool; run tool-seed
printf 'public class P0 { public static int Value() => 1 + 0; public static int Added() => 2; }\n' > P0/Code.cs
run tool-body; counts 1 2
# Add an explicit SDK-selected grandchild reference. It must invalidate P2
# even when P1's own reference assembly remains unchanged.
sed -i 's|<Target Name="DropUnusedCompilerReference".*</Target>||' P2/P2.csproj
sed -i 's|</Project>|<ItemGroup><ProjectReference Include="../P0/P0.csproj" /></ItemGroup></Project>|' P2/P2.csproj
mapping transitive; sync transitive; run transitive-seed
printf 'public class P0 { public static int Value() => 1; public static int Added() => 2; public static int More() => 3; }\n' > P0/Code.cs
run transitive-api; counts 0 3
products > "$TEST_TMPDIR/transitive.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/transitive-clean.log" 2>&1
run transitive-fresh
products > "$TEST_TMPDIR/transitive-fresh.sha256"
cmp "$TEST_TMPDIR/transitive.sha256" "$TEST_TMPDIR/transitive-fresh.sha256"
echo 'PASS: complete compiler inputs exclude unused edges, retain real transitive/tool reads, reject missing/stale inventories, and match fresh bytes'
