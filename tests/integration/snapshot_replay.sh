#!/usr/bin/env bash
# Verify production replay bytes once, then reuse that digest in dependency keys.
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel build @dotnet//:files > "$TEST_TMPDIR/sdk.log" 2>&1 || { cat "$TEST_TMPDIR/sdk.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
cp -a "$sdk" "$scratch/proof-sdk"
mkdir "$scratch/proof"
cp "$runner_dir/SnapshotReplay.cs.txt" "$scratch/proof/Program.cs"
for file in FileMaterializer Contract GraphProfile; do cp "$scratch/msbuild-bazel/tools/GraphBuild/$file.cs" "$scratch/proof/"; done
cat > "$scratch/proof/Proof.csproj" <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>
XML
"$scratch/proof-sdk/dotnet" build "$scratch/proof/Proof.csproj" -c Release -p:UseSharedCompilation=false > "$TEST_TMPDIR/proof-build.log" 2>&1 || { cat "$TEST_TMPDIR/proof-build.log" >&2; exit 1; }
"$scratch/proof-sdk/dotnet" "$scratch/proof/bin/Release/net10.0/Proof.dll" "$scratch/bytes"
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1 --disk_cache= --remote_cache=)
run() {
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/$1.log")" == "$2" ]]
}
run seed 1
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run body 2
python3 - <<'PY'
import json
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==(2,1),r
assert r['materialization']['verifiedCopies']>0,r
assert r['operations']['verifiedOutputDigest']['calls']==r['materialization']['verifiedCopies'],r
print('PASS: request-scoped replay digests',r['materialization']['verifiedCopies'])
PY
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
products > "$TEST_TMPDIR/replay.sha256"
bazel shutdown
bazel clean > "$TEST_TMPDIR/clean.log" 2>&1
run fresh 2
products > "$TEST_TMPDIR/fresh.sha256"
cmp "$TEST_TMPDIR/replay.sha256" "$TEST_TMPDIR/fresh.sha256"
echo 'PASS: replayed and fresh graph products match'
