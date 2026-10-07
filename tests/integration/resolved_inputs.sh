#!/usr/bin/env bash
# SDK-selected inputs are captured by sync without dependency-specific mappings.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
sed -i 's|</Project>|<Target Name="DropUnusedCompilerReference" BeforeTargets="FindReferenceAssembliesForReferences"><ItemGroup><ReferencePath Remove="@(ReferencePath)" Condition="\x27%(Filename)\x27 == \x27P0\x27" /></ItemGroup></Target></Project>|' P2/P2.csproj
mapping() {
    python3 - "$1" <<'PY'
import hashlib,json,sys
from pathlib import Path
binding={}
if '<Target ' in Path('P2/P2.csproj').read_text():
    binding['documents']={'P2/P2.csproj':dict(sha256=hashlib.sha256(Path('P2/P2.csproj').read_bytes()).hexdigest(),targets=['DropUnusedCompilerReference'],tasks=[],inputs=[])}
if sys.argv[1]=='tool': binding['implementationDependencies']=['P1/P1.csproj']
Path('resolved.json').write_text(json.dumps(dict(projectDefaults=dict(referenceBoundary=True,preparedRestore=True),projects={'P2/P2.csproj':binding})))
PY
}
mapping narrow
sed -i 's/projects = \["P2\/P2.csproj"\]/projects = ["P2\/P2.csproj"], mappings = "resolved.json", package_build = True, resolve_references = True/' BUILD.bazel
sync() { bazel run //:sync > "$TEST_TMPDIR/$1-sync.log" 2>&1 || { cat "$TEST_TMPDIR/$1-sync.log" >&2; exit 1; }; }
sync seed
[[ ! -d P0/bin && ! -d P1/obj ]]
python3 - <<'PY'
import json
c=json.load(open('graph.generated.json'))
assert c['Version']==10
p=c['Projects']['P2/P2.csproj']['Configurations'][0]
assert p['CompilerReferencesComplete'] and set(p['CompilerReferences'])=={'P1/P1.csproj'},p
assert p['DependencyCopies']['P2/bin/Release/net10.0/P0.dll']=='P1/bin/Release/net10.0/P0.dll',p
PY
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() { bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }; [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]; }
counts() {
    python3 - "$1" "$2" <<'PY'
import json,sys
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==(int(sys.argv[1]),int(sys.argv[2])),r
PY
}
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
run seed 1; counts 0 3
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run body 2; counts 2 1
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
run api 2; counts 1 2
products > "$TEST_TMPDIR/api.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh 2; products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/fresh.sha256"
# Capture an implementation DLL selected by the SDK, rather than hardcoding it.
sed -i 's|</PropertyGroup>|<ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup>|' P1/P1.csproj
sed -i 's|Include="../P1/P1.csproj"|Include="../P1/P1.csproj" SkipUseReferenceAssembly="true"|' P2/P2.csproj
mapping implementation; sync implementation
python3 - <<'PY'
import json
p=json.load(open('graph.generated.json'))['Projects']['P2/P2.csproj']['Configurations'][0]
assert p['CompilerReferences']=={'P1/P1.csproj':'P1/bin/Release/net10.0/P1.dll'},p
PY
run implementation-seed 2
printf 'public class P0 { public static int Value() => 2 + 0; public static int Added() => 3; }\n' > P0/Code.cs
run implementation-body 2; counts 2 1
printf 'public class P1 { public static int Value() => P0.Value() + 0; }\n' > P1/Code.cs
run implementation-producer 2; counts 1 2
products > "$TEST_TMPDIR/implementation.sha256"
bazel shutdown; bazel clean > "$TEST_TMPDIR/implementation-clean.log" 2>&1
run implementation-fresh 2; products > "$TEST_TMPDIR/implementation-fresh.sha256"
cmp "$TEST_TMPDIR/implementation.sha256" "$TEST_TMPDIR/implementation-fresh.sha256"
mapping tool; sync tool; run tool-seed 2
printf 'public class P0 { public static int Value() => 2 + 0 + 0; public static int Added() => 3; }\n' > P0/Code.cs
run tool-body 2; counts 1 2
echo 'PASS: generic sync captures SDK reference/implementation/copy selections, narrows invalidation, retains tool roles, and matches fresh bytes'
