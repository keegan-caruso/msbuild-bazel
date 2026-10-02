#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
cp BUILD.bazel.in BUILD.bazel
bazel run //:sync
cat >> BUILD.bazel <<EOF
load(":graph.generated.bzl", "app_graph")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")
app_graph(name="graph", linux_stable_paths=True, linux_worker=True, worker_cache_mb=$WORKER_CACHE_MB)
msbuild_graph_binary(name="app", graph=":graph", project="P2/P2.csproj")
EOF
reused=2; replay=3; api=1
if [[ "$WORKER_CACHE_MB" == 0 ]]; then reused=0; replay=0; api=0; fi
report=bazel-bin/graph.graph/report.json

build() {
    local label="$1" value="$2" hits="$3" strategy="${4:-worker}"
    bazel run //:app --strategy="MSBuildGraph=$strategy" --worker_sandboxing \
        --worker_max_instances=MSBuildGraph=1 > "$TEST_TMPDIR/$label.log" 2>&1 || {
        cat "$TEST_TMPDIR/$label.log" >&2; exit 1;
    }
    [[ "$(tail -n 1 "$TEST_TMPDIR/$label.log")" == "$value" ]] || {
        cat "$TEST_TMPDIR/$label.log" >&2; exit 1;
    }
    grep -Eq '"hits"[[:space:]]*:[[:space:]]*'"$hits"'([,[:space:]]|$)' "$report" &&
        grep -Eq '"misses"[[:space:]]*:[[:space:]]*'"$((3 - hits))"'([,[:space:]]|$)' "$report" || {
        cat "$report" >&2; exit 1;
    }
    echo "PASS $label (expected hits=$hits, value=$value)"
}

# All owned files, not just assemblies, must match the fresh sandboxed build.
# MSBuild's AssemblyReference.cache carries staging paths, not runtime output.
outputs() {
    (cd bazel-bin/graph.graph/workspace
     { find P*/bin P*/obj/Release -type f ! -name '*.AssemblyReference.cache' -print0
       find P*/obj -maxdepth 1 -type f -name '*.json' -print0; } |
         sort -z | xargs -0 sha256sum)
}

expect_failure() {
    local label="$1" error="$2"
    if bazel run //:app --strategy=MSBuildGraph=worker --worker_sandboxing \
        --worker_max_instances=MSBuildGraph=1 > "$TEST_TMPDIR/$label.log" 2>&1; then
        echo "Unexpected success: $label" >&2; exit 1
    fi
    assert_contains "$TEST_TMPDIR/$label.log" "$error"
}

build seed 1 0
cat > P0/Code.cs <<'EOF'
public class P0 { public static int Value() => 2; }
EOF
build body 2 "$reused"
outputs > "$TEST_TMPDIR/body.sha256"
# Enabling profiling changes the action but preserves the worker snapshot.
sed -i 's/linux_worker=True,/linux_worker=True, profile_build=True,/' BUILD.bazel
build profiled-replay 2 "$replay"
outputs > "$TEST_TMPDIR/profiled.sha256"
cmp "$TEST_TMPDIR/body.sha256" "$TEST_TMPDIR/profiled.sha256"
assert_contains "$report" '"worker"'
# Worker timing fields are flat numeric JSON; check the original phase bounds.
sed 's/.*"worker":{//; s/}.*//' "$report" | awk -F '[:,]' '
    BEGIN { total = -1; child = -1; staging = -1 }
    {
        for (i = 1; i < NF; i += 2) {
            if ($i == "\"totalSeconds\"") total = $(i + 1)
            if ($i == "\"childSeconds\"") child = $(i + 1)
            if ($i == "\"stagingSeconds\"") staging = $(i + 1)
        }
        exit !(total >= child && child > 0 && staging >= 0)
    }'

assert_contains "$report" '"operations":{'
sed -i 's/ profile_build=True,//' BUILD.bazel
build unprofiled-replay 2 "$replay"
assert_contains "$report" '"operations":null'
if grep -Fq '"worker"' "$report"; then echo 'Unexpected worker profiling' >&2; exit 1; fi

# API edit recompiles P1, but P2 can reuse its unchanged direct reference boundary.
cat > P0/Code.cs <<'EOF'
public class P0 { public static int Value() => 2; public static int Extra() => 3; }
EOF
build leaf-api 2 "$api"
outputs > "$TEST_TMPDIR/api.sha256"
cat > P1/Code.cs <<'EOF'
public class P1 { public static int Value() => P0.Value(); public static int Extra() => 4; }
EOF
build propagated-api 2 "$api"
# Preserve the original failure/property/Build and Publish parity controls.
printf 'this is invalid C#\n' > P0/Code.cs
expect_failure compile-failure 'error CS'
printf 'public class P0 { public static int Value() => 3; public static int Extra() => 3; }\n' > P0/Code.cs
build after-failure 3 "$reused"
sed -i 's/latest/preview/' Directory.Build.props
expect_failure stale-definition 'Graph definition changed'
bazel run //:sync
build property 3 0
sed -i 's/preview/latest/' Directory.Build.props
printf 'public class P0 { public static int Value() => 2; }\n' > P0/Code.cs
printf 'public class P1 { public static int Value() => P0.Value(); }\n' > P1/Code.cs
bazel run //:sync
bazel shutdown
bazel clean
build native-body-control 2 0 linux-sandbox
outputs > "$TEST_TMPDIR/native-body.sha256"
cmp "$TEST_TMPDIR/body.sha256" "$TEST_TMPDIR/native-body.sha256"
printf 'public class P0 { public static int Value() => 2; public static int Extra() => 3; }\n' > P0/Code.cs
build native-api-control 2 0 linux-sandbox
outputs > "$TEST_TMPDIR/native-api.sha256"
cmp "$TEST_TMPDIR/api.sha256" "$TEST_TMPDIR/native-api.sha256"
sed -i 's/linux_worker=True,/linux_worker=True, target="Publish",/' BUILD.bazel
build publish 2 0
printf 'public class P0 { public static int Value() => 4; public static int Extra() => 3; }\n' > P0/Code.cs
build publish-body 4 "$reused"
outputs > "$TEST_TMPDIR/publish.sha256"
bazel shutdown
bazel clean
build publish-native-control 4 0 linux-sandbox
outputs > "$TEST_TMPDIR/publish-native.sha256"
cmp "$TEST_TMPDIR/publish.sha256" "$TEST_TMPDIR/publish-native.sha256"
echo 'PASS: worker body/API reuse, failure recovery, property invalidation, profiling and native Build/Publish parity'
