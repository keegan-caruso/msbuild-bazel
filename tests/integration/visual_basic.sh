#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
app_graph(name="graph")
msbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")
msbuild_graph_test(name="test",graph=":graph",project="App/App.csproj")
BUILD
options=(--remote_cache= "--disk_cache=$scratch/action-cache")
run() {
    bazel run //:app "${options[@]}" > "$TEST_TMPDIR/$1.log" 2>&1 || { cat "$TEST_TMPDIR/$1.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1.log" "VB:$2"
}
run seed 1
sed -i.bak 's/Return 1/Return 2/' Library/Code.vb
rm Library/Code.vb.bak
run body 2
bazel run //:sync -- --check
bazel test //:test "${options[@]}" --test_output=errors
bazel shutdown
rm -rf "$scratch/bazel"
run independent-recovery 2
# A changed VB input must also invalidate a recovered whole-graph action.
sed -i.bak 's/Return 2/Return 3/' Library/Code.vb
rm Library/Code.vb.bak
run recovered-edit 3
echo 'PASS: explicit VB root/mapping, C# consumer, body invalidation, execution and independent cache recovery'
