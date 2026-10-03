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
    # Source/Restore staging is private; consumers receive owned products only.
    for input in P0/Code.cs global.json .package-source .nuget; do
        if [[ -e "bazel-bin/graph.graph/workspace/$input" ]]; then
            echo "Published staged input: $input" >&2; exit 1
        fi
    done
    echo "PASS $label (expected hits=$hits, value=$value)"
}

# All owned files, not just assemblies, must match the fresh sandboxed build.
# MSBuild's AssemblyReference.cache carries staging paths, not runtime output.
outputs() {
    (cd bazel-bin/graph.graph/workspace
     find P*/bin P*/obj/Release -type f ! -name '*.AssemblyReference.cache' -print0 |
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

# A generated targeting-pack tree is a declared input to a separate graph.
mkdir Consumer
cat > Consumer/App.csproj <<'EOF'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="P0"><HintPath>../prepared/P0.dll</HintPath></Reference></ItemGroup></Project>
EOF
printf 'System.Console.WriteLine(P0.Value());\n' > Consumer/Code.cs
cat > consumer.json <<'EOF'
{"Version":1,"Entry":"Consumer/App.csproj","SdkVersion":"10.0.400","Properties":{"Configuration":"Release"},"SharedInputs":["Directory.Build.props","global.json"],"Projects":{"Consumer/App.csproj":{"Inputs":["Consumer/App.csproj","Consumer/Code.cs","prepared/P0.dll","prepared/P0.pdb","prepared/P0.deps.json"],"OutputDirectories":["Consumer/bin/Release/net10.0","Consumer/obj/Release/net10.0"]}}}
EOF
cat >> BUILD.bazel <<'EOF'
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_output")
msbuild_graph_output(name="references", graph=":graph", path="P0/bin/Release/net10.0", directory=True)
msbuild_graph(name="consumer", runner=":graph_runner", contract="consumer.json", srcs=["Consumer/App.csproj","Consumer/Code.cs","Directory.Build.props","global.json"], input_paths={":references":"prepared"}, project_outputs={"Consumer/App.csproj|net10.0":["Consumer/bin/Release/net10.0","App.dll","Exe"]}, linux_stable_paths=True, linux_worker=True)
msbuild_graph_binary(name="consumer_app", graph=":consumer", project="Consumer/App.csproj")
EOF
for strategy in linux-sandbox worker; do
    printf '// %s\n' "$strategy" >> Consumer/Code.cs
    bazel run //:consumer_app --strategy="MSBuildGraph=$strategy" --worker_sandboxing > "$TEST_TMPDIR/tree-$strategy.log" 2>&1 || { cat "$TEST_TMPDIR/tree-$strategy.log" >&2; exit 1; }
    [[ "$(tail -1 "$TEST_TMPDIR/tree-$strategy.log")" == 4 ]]
done
sed -i 's/Value() => 4/Value() => 5/' P0/Code.cs
bazel run //:consumer_app --strategy=MSBuildGraph=worker --worker_sandboxing > "$TEST_TMPDIR/tree-edit.log" 2>&1 || { cat "$TEST_TMPDIR/tree-edit.log" >&2; exit 1; }
[[ "$(tail -1 "$TEST_TMPDIR/tree-edit.log")" == 5 ]]
cat >> BUILD.bazel <<'EOF'
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_test")
msbuild_graph_test(name="exit_contract", graph=":consumer", project="Consumer/App.csproj", expected_exit_code=100)
EOF
printf 'return 100;\n' > Consumer/Code.cs
bazel test //:exit_contract --strategy=MSBuildGraph=worker --worker_sandboxing --test_output=errors
printf 'return 0;\n' > Consumer/Code.cs
if bazel test //:exit_contract --strategy=MSBuildGraph=worker --worker_sandboxing --test_output=errors > "$TEST_TMPDIR/exit-contract.log" 2>&1; then
    echo 'Unexpected zero exit satisfied the 100 contract' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/exit-contract.log" 'Expected exit code 100, received 0'
sed -i 's/input_paths={":references":"prepared"}/input_paths={}/' BUILD.bazel
if bazel run //:consumer_app --strategy=MSBuildGraph=worker --worker_sandboxing > "$TEST_TMPDIR/tree-missing.log" 2>&1; then
    echo 'Missing generated reference tree unexpectedly succeeded' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/tree-missing.log" 'Declared graph input is missing'
echo 'PASS: generated tree handoff, producer invalidation, missing-tree rejection and return-100 pass/fail'

# Prepared Restore metadata is also an owned producer artifact.
cat > restore-consumer.json <<'EOF'
{"Version":4,"Entry":"Consumer/App.csproj","SdkVersion":"10.0.400","Properties":{"Configuration":"Release"},"SharedInputs":["Directory.Build.props","global.json"],"Projects":{"Consumer/App.csproj":{"Inputs":["Consumer/App.csproj","Consumer/Code.cs"],"OutputDirectories":["Consumer/bin/Release/net10.0","Consumer/obj/Release/net10.0"]}},"Restore":{"Inputs":["Consumer/App.csproj","Directory.Build.props","global.json"],"Outputs":["Consumer/obj/project.assets.json","Consumer/obj/project.nuget.cache","Consumer/obj/App.csproj.nuget.dgspec.json","Consumer/obj/App.csproj.nuget.g.props","Consumer/obj/App.csproj.nuget.g.targets"]}}
EOF
cat >> BUILD.bazel <<'EOF'
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_restore")
msbuild_graph_restore(name="consumer_restore", runner=":graph_runner", contract="restore-consumer.json", srcs=["Consumer/App.csproj","Directory.Build.props","global.json"], linux_stable_paths=True)
msbuild_graph_output(name="consumer_assets", graph=":consumer_restore", path="Consumer/obj", directory=True)
EOF
bazel build //:consumer_assets
[[ -f bazel-bin/consumer_assets/obj/project.assets.json ]]
[[ -f bazel-bin/consumer_assets/obj/App.csproj.nuget.g.props ]]
echo 'PASS: prepared Restore output tree export'
