#!/usr/bin/env bash
# Compare public sync/check with and without a declared, cacheable workspace.
set -euo pipefail
if [[ $# -lt 2 ]]; then
    echo 'Usage: cached_preparation_benchmark.sh OUTPUT RULES_CHECKOUT [ROOT_COUNTS...]' >&2
    exit 2
fi
output=$1
rules=$2
shift 2
if [[ $# == 0 ]]; then set -- 1 16 64; fi
bazel_binary=${RULES_MSBUILD_BAZEL:?Set RULES_MSBUILD_BAZEL to the pinned Bazel launcher}
mkdir "$output"
printf 'roots,case,sample,seconds\n' > "$output/timings.csv"
workspace=''
base=''
bazel() {
    local command=$1; shift
    local options=()
    case $command in
        run|fetch) if [[ -n ${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-} ]]; then options+=("--repository_cache=$RULES_MSBUILD_TEST_REPOSITORY_CACHE"); fi ;;
    esac
    if [[ $command == run && -n ${SYNC_PREPARE_CACHE_URL:-} ]]; then options+=("--remote_cache=$SYNC_PREPARE_CACHE_URL" --disk_cache=); fi
    (cd "$workspace"; "$bazel_binary" --nosystem_rc --nohome_rc --noworkspace_rc "--output_base=$base" "$command" ${options[@]+"${options[@]}"} "$@")
}
cleanup() { if [[ -n $base ]]; then bazel shutdown >/dev/null 2>&1 || true; fi; }
trap cleanup EXIT
run() {
    local case_name=$1 sample=$2 target=$3; shift 3
    TIMEFORMAT=%R
    if ! { time bazel run "//:$target" --execution_log_json_file="$output/$size-$case_name-$sample.actions.json" -- "$@" > "$output/$size-$case_name-$sample.log" 2>&1; } 2> "$output/elapsed"; then
        cat "$output/$size-$case_name-$sample.log" >&2
        exit 1
    fi
    printf '%s,%s,%s,%s\n' "$size" "$case_name" "$sample" "$(cat "$output/elapsed")" | tee -a "$output/timings.csv"
}
for size in "$@"; do
    case $size in ''|*[!0-9]*) echo 'Root counts must be positive integers' >&2; exit 2 ;; esac
    if ((size<1)); then echo 'Root counts must be positive integers' >&2; exit 2; fi
    workspace="$output/workspace-$size"
    base="$output/bazel-$size"
    mkdir "$workspace"
    cp "$rules/global.json" "$rules/.bazelversion" "$workspace/"
    cat > "$workspace/MODULE.bazel" <<MODULE
module(name="preparation_benchmark")
bazel_dep(name="rules_msbuild", version="0.0.0")
local_path_override(module_name="rules_msbuild", path="$rules")
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name="dotnet", global_json="//:global.json")
use_repo(dotnet, "dotnet")
register_toolchains("@dotnet//:all")
MODULE
    entries=()
    for ((i=0; i<3+size; i++)); do
        if ((i<3)); then name=Shared$i; dependency=Shared$((i+1)); else name=Root$((i-3)); dependency=Shared0; entries+=("\"$name/$name.csproj\""); fi
        mkdir "$workspace/$name"
        {
            printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'
            if ((i!=2)); then printf '<ItemGroup><ProjectReference Include="../%s/%s.csproj" /></ItemGroup>' "$dependency" "$dependency"; fi
            printf '</Project>'
        } > "$workspace/$name/$name.csproj"
        printf 'public class %s { public int Value() => 1; }\n' "$name" > "$workspace/$name/Code.cs"
    done
    projects=$(IFS=,; echo "${entries[*]}")
    cat > "$workspace/BUILD.bazel" <<BUILD
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
msbuild_sync(name="baseline", projects=[$projects], package_build=True, resolve_references=True)
msbuild_sync(name="sync", projects=[$projects], srcs=glob(["Root*/**", "Shared*/**", "global.json"]), package_build=True, resolve_references=True)
BUILD
    # Acquire SDK/registry facts before timing. Cold rows include runner bootstrap.
    bazel fetch //:baseline //:sync > "$output/$size-fetch.log" 2>&1
    run cold-baseline 0 baseline
    cp "$workspace/graph.generated.json" "$output/$size.expected.json"
    cp "$workspace/graph.generated.bzl" "$output/$size.expected.bzl"
    run cold-cached 0 sync
    cmp "$output/$size.expected.json" "$workspace/graph.generated.json"
    cmp "$output/$size.expected.bzl" "$workspace/graph.generated.bzl"
    for sample in 1 2 3; do
        order=(baseline sync)
        if ((sample==2)); then order=(sync baseline); fi
        for target in "${order[@]}"; do run "$target-check" "$sample" "$target" --check; done
    done
    cleanup
    base=''
done
