#!/usr/bin/env bash
# Conditional defaults follow the selected execution platform and closed inputs.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
: "${QUALIFICATION_CACHE_URL:?Set an HTTP AC/CAS endpoint}"
printf '<!-- Defaults control: %s -->\n' "${scratch##*/}" >> Directory.Build.props
printf '\nbazel_dep(name="platforms", version="1.0.0")\n' >> MODULE.bazel
cat > BUILD.bazel <<'BUILD'
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
platform(name="qualified", constraint_values=["@platforms//os:linux", "@platforms//cpu:aarch64", "@rules_msbuild//msbuild:qualified_linux_bwrap"])
msbuild_sync(name="sync", projects=["P2/P2.csproj"], srcs=glob(["P*/**", "global.json", "Directory.Build.*"]))
msbuild_sync(name="forced", projects=["P2/P2.csproj"], srcs=glob(["P*/**", "global.json", "Directory.Build.*"]), qualification_cache=True)
msbuild_sync(name="disabled", projects=["P2/P2.csproj"], srcs=glob(["P*/**", "global.json", "Directory.Build.*"]), package_build=False, qualification_cache=False, seed_build_cache=False)
BUILD
run_sync() {
    local label=$1; shift
    bazel run //:sync "$@" > "$TEST_TMPDIR/$label.log" 2>&1 || { cat "$TEST_TMPDIR/$label.log" >&2; return 1; }
}
run_sync portable
# A target marker alone cannot enable execution-platform behavior.
run_sync target_only --platforms=//:qualified --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL"
if grep -q PROJECT_SYNC_CACHE "$TEST_TMPDIR/target_only.log"; then cat "$TEST_TMPDIR/target_only.log"; exit 1; fi
run_sync no_endpoint --extra_execution_platforms=//:qualified
if grep -q PROJECT_SYNC_CACHE "$TEST_TMPDIR/no_endpoint.log"; then cat "$TEST_TMPDIR/no_endpoint.log"; exit 1; fi
if bazel run //:forced > "$TEST_TMPDIR/forced.log" 2>&1; then cat "$TEST_TMPDIR/forced.log"; exit 1; fi
assert_contains "$TEST_TMPDIR/forced.log" 'qualification_cache requires'
bazel run //:disabled --extra_execution_platforms=//:qualified --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" > "$TEST_TMPDIR/disabled.log" 2>&1 || { cat "$TEST_TMPDIR/disabled.log"; exit 1; }
if grep -q PROJECT_SYNC_CACHE "$TEST_TMPDIR/disabled.log"; then cat "$TEST_TMPDIR/disabled.log"; exit 1; fi
run_sync qualified --extra_execution_platforms=//:qualified --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL"
assert_contains "$TEST_TMPDIR/qualified.log" '"compilations":3'
assert_contains "$TEST_TMPDIR/qualified.log" 'GRAPH_CACHE_SEED'
python3 - <<'PY'
import json
c=json.load(open('graph.generated.json'))
assert 'P0/Code.cs' in c['Restore']['Inputs'], c['Restore']
assert 'P0/Code.cs' not in c['SharedInputs'], c['SharedInputs']
PY
cat >> BUILD.bazel <<'BUILD'
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", profile_build=True)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
BUILD
options=(--extra_execution_platforms=//:qualified --action_env="RULES_MSBUILD_PROJECT_CACHE_URL=$QUALIFICATION_CACHE_URL" --remote_cache= --disk_cache=)
run_app() {
    local label=$1 expected=$2 hits=$3 misses=$4
    shift 4
    bazel run //:app "${options[@]}" "$@" > "$TEST_TMPDIR/$label.log" 2>&1 || { cat "$TEST_TMPDIR/$label.log" >&2; return 1; }
    [[ $(tail -1 "$TEST_TMPDIR/$label.log") == "$expected" ]]
    python3 - "$hits" "$misses" <<'PY'
import json,sys
r=json.load(open('bazel-bin/graph.graph/report.json'))
assert (r['hits'],r['misses'])==tuple(map(int,sys.argv[1:])),r
PY
}
run_app seeded 1 3 0
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
run_app body 2 2 1
products() { (cd bazel-bin/graph.graph/workspace; find P*/bin P*/obj -type f \( -name '*.dll' -o -name '*.pdb' \) -print0 | sort -z | xargs -0 sha256sum); }
products > "$TEST_TMPDIR/body.sha256"
run_app body_fresh 2 0 3 --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=
products > "$TEST_TMPDIR/body-fresh.sha256"
cmp "$TEST_TMPDIR/body.sha256" "$TEST_TMPDIR/body-fresh.sha256"
printf 'public class P0 { public static int Value() => 2; public static int Added() => 3; }\n' > P0/Code.cs
run_app api 2 1 2
products > "$TEST_TMPDIR/api.sha256"
run_app api_fresh 2 0 3 --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=
products > "$TEST_TMPDIR/api-fresh.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/api-fresh.sha256"
# Explicit False retains the portable path even on the qualified execution platform.
sed -i 's/app_graph(name="graph", profile_build=True)/app_graph(name="graph", linux_stable_paths=False)/' BUILD.bazel
bazel run //:app "${options[@]}" > "$TEST_TMPDIR/false.log" 2>&1 || { cat "$TEST_TMPDIR/false.log" >&2; exit 1; }
[[ $(tail -1 "$TEST_TMPDIR/false.log") == 2 ]]
cat >> BUILD.bazel <<'BUILD'
msbuild_sync(name="invalid_seed", projects=["P2/P2.csproj"], seed_build_cache=True)
BUILD
if bazel run //:invalid_seed > "$TEST_TMPDIR/invalid-seed.log" 2>&1; then cat "$TEST_TMPDIR/invalid-seed.log"; exit 1; fi
assert_contains "$TEST_TMPDIR/invalid-seed.log" 'seed_build_cache requires srcs'
echo 'PASS: closed SDK defaults, execution-platform/endpoint fallback, seeded Build, body/API reuse and explicit portable override'
