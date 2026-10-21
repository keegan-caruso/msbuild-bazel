#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
: "${QUALIFICATION_CACHE_URL:?Set an HTTP AC/CAS endpoint}"
# Isolate this producer's cold row from previous runs sharing the HTTP cache.
printf '<!-- Qualification cache control: %s -->\n' "${scratch##*/}" >> Directory.Build.props
mkdir Other
printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>\n' > Other/Other.csproj
printf 'public class Other {}\n' > Other/Code.cs
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="baseline", projects=["P2/P2.csproj", "Other/Other.csproj"], package_build=True, resolve_references=True)
msbuild_sync(name="sync", projects=["P2/P2.csproj", "Other/Other.csproj"], srcs=glob(["P*/**", "Other/**", "global.json", "Directory.Build.*"]), package_build=True, resolve_references=True, qualification_cache=True)
BUILD
run() {
    local name=$1; shift
    bazel run //:sync --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" "$@" > "$TEST_TMPDIR/$name.log" 2>&1 || { cat "$TEST_TMPDIR/$name.log" >&2; return 1; }
}
report() {
    assert_contains "$TEST_TMPDIR/$1.log" "\"hits\":$2,\"misses\":$3,\"uncacheable\":0,\"compilations\":$4"
}
bazel run //:baseline > "$TEST_TMPDIR/baseline.log" 2>&1 || { cat "$TEST_TMPDIR/baseline.log" >&2; exit 1; }
cp graph.generated.json "$TEST_TMPDIR/baseline.json"
cp graph.generated.bzl "$TEST_TMPDIR/baseline.bzl"
run cold
report cold 0 4 4
cmp graph.generated.json "$TEST_TMPDIR/baseline.json"
cmp graph.generated.bzl "$TEST_TMPDIR/baseline.bzl"
# Force just preparation to execute again; its ephemeral project cache is empty.
# Bootstrap still uses the same runner bytes. The HTTP cache supplies all projects.
run recovered --action_env=RULES_MSBUILD_SYNC_PROFILE=1 -- --check
report recovered 4 0 0
assert_contains "$TEST_TMPDIR/recovered.log" '"phase":"private-build"'
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run body
report body 1 3 3
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
run api
report api 1 3 3
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph")
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
bazel run //:app --remote_cache= --disk_cache= > "$TEST_TMPDIR/app.log" 2>&1 || { cat "$TEST_TMPDIR/app.log" >&2; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/app.log") == 2 ]]
# Removing the source edits recovers the original snapshots and declarations.
printf 'public class P0 { public static int Value() => 1; }\n' > P0/Code.cs
run restored
report restored 4 0 0
cmp graph.generated.json "$TEST_TMPDIR/baseline.json"
cmp graph.generated.bzl "$TEST_TMPDIR/baseline.bzl"
echo 'PASS: per-project qualification HTTP recovery, independent branch reuse, body/API invalidation and app execution'
