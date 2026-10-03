#!/usr/bin/env bash
set -euo pipefail
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$runner_dir/common.sh"
cp BUILD.bazel.in BUILD.bazel
# Take raw controls before sync writes generated graph files.
cp -R "$scratch/consumer" "$scratch/authored"
bazel build @dotnet//:files @traversal_sdk//file > "$TEST_TMPDIR/bootstrap.log" 2>&1 || { cat "$TEST_TMPDIR/bootstrap.log" >&2; exit 1; }
execroot=$(bazel info execution_root)
sdk=$(dirname "$(realpath "$execroot/$(bazel cquery @dotnet//:files --output=files 2> "$TEST_TMPDIR/sdk-query.log" | grep '/sdk/dotnet$')")")
archive=$(realpath "$execroot/$(bazel cquery @traversal_sdk//file --output=files 2> "$TEST_TMPDIR/package-query.log")")
bash "$runner_dir/traversal_raw.sh" "$sdk" "$archive" "$scratch/authored" "$scratch/raw"
bazel run //:sync > "$TEST_TMPDIR/sync.log" 2>&1 || { cat "$TEST_TMPDIR/sync.log" >&2; exit 1; }
bazel run //:sync -- --check
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True)
msbuild_graph_binary(name="app", graph=":graph", project="src/App/App.csproj")
msbuild_graph_test(name="tests", graph=":graph", project="tests/Tests/Tests.csproj")
BUILD
options=(--strategy=MSBuildGraph=worker --worker_sandboxing --worker_max_instances=MSBuildGraph=1)
bazel run //:app "${options[@]}" > "$TEST_TMPDIR/seed.log" 2>&1 || { cat "$TEST_TMPDIR/seed.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/seed.log")" == 1 ]]
report=bazel-bin/graph.graph/report.json
assert_contains "$report" '"hits":0'
assert_contains "$report" '"misses":3'
(cd bazel-bin/graph.graph/workspace; find . -path '*/bin/*' -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum) > "$TEST_TMPDIR/graph.sha256"
cmp "$scratch/raw/graph.sha256" "$TEST_TMPDIR/graph.sha256"
bazel test //:tests "${options[@]}" --nocache_test_results --test_output=errors
# Traversal inputs/Restore state must not be published as products.
[[ ! -e bazel-bin/graph.graph/workspace/dirs.proj && ! -e bazel-bin/graph.graph/workspace/bin && ! -e bazel-bin/graph.graph/workspace/src/bin ]]
echo 'PASS: traversal public sync, prepared Restore, worker build, raw byte parity and Bazel test'

source "$runner_dir/traversal_helpers.sh"
case "${TRAVERSAL_SLICE:-all}" in
    all) source "$runner_dir/traversal_selection.sh"; source "$runner_dir/traversal_edits.sh"; source "$runner_dir/traversal_targets.sh" ;;
    selection) source "$runner_dir/traversal_selection.sh" ;;
    edits) source "$runner_dir/traversal_edits.sh" ;;
    targets) source "$runner_dir/traversal_targets.sh" ;;
    *) echo 'TRAVERSAL_SLICE must be all, selection, edits or targets' >&2; exit 2 ;;
esac
