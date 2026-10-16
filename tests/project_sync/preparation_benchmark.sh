#!/usr/bin/env bash
# Compare two built ProjectSync payloads. Reports and fixtures stay outside Git.
set -euo pipefail
if [[ $# -lt 3 ]]; then
    echo 'Usage: preparation_benchmark.sh OUTPUT BASELINE/ProjectSync.dll CANDIDATE/ProjectSync.dll [ROOT_COUNTS...]' >&2
    exit 2
fi
output=$1
baseline=$2
candidate=$3
shift 3
if [[ $# == 0 ]]; then set -- 1 4 16 64; fi
sdk_root=${RULES_MSBUILD_DOTNET_ROOT:?Set RULES_MSBUILD_DOTNET_ROOT to the pinned SDK}
sdk_version=$("$sdk_root/dotnet" --version)
mkdir "$output"
printf 'roots,projects,phase,sample,runner,seconds\n' > "$output/timings.csv"
for size in "$@"; do
    case $size in ''|*[!0-9]*) echo 'Root counts must be positive integers' >&2; exit 2 ;; esac
    if ((size<1)); then echo 'Root counts must be positive integers' >&2; exit 2; fi
    workspace="$output/$size"
    mkdir "$workspace"
    entries=()
    for ((i=0; i<3+size; i++)); do
        if ((i<3)); then
            name=Shared$i
            dependency=Shared$((i+1))
        else
            name=Root$((i-3))
            dependency=Shared0
            entries+=("$name/$name.csproj")
        fi
        mkdir "$workspace/$name"
        {
            printf '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'
            if ((i!=2)); then
                printf '<ItemGroup><ProjectReference Include="../%s/%s.csproj" /></ItemGroup>' "$dependency" "$dependency"
            fi
            printf '</Project>'
        } > "$workspace/$name/$name.csproj"
        printf 'public class %s { public int Value() => 1; }\n' "$name" > "$workspace/$name/Code.cs"
    done
    for phase in sync qualified; do
        flags=(--package-build)
        if [[ $phase == qualified ]]; then flags+=(--resolve-references); fi
        for sample in 1 2 3; do
            order=(baseline candidate)
            if ((sample==2)); then order=(candidate baseline); fi
            for runner in "${order[@]}"; do
                payload=$baseline
                if [[ $runner == candidate ]]; then payload=$candidate; fi
                check=()
                if ((sample>1)); then check=(--check); fi
                log="$output/$size-$phase-$sample-$runner.log"
                TIMEFORMAT=%R
                if ! { time "$sdk_root/dotnet" "$payload" "$workspace" "$sdk_root/sdk/$sdk_version" "${entries[@]}" "${flags[@]}" ${check[@]+"${check[@]}"} > "$log" 2>&1; } 2> "$output/elapsed"; then
                    cat "$log" >&2
                    exit 1
                fi
                seconds=$(cat "$output/elapsed")
                printf '%s,%s,%s,%s,%s,%s\n' "$size" "$((size+3))" "$phase" "$sample" "$runner" "$seconds" | tee -a "$output/timings.csv"
                for suffix in json bzl; do
                    expected="$output/$size-$phase.generated.$suffix"
                    if [[ $sample == 1 && $runner == baseline ]]; then
                        cp "$workspace/graph.generated.$suffix" "$expected"
                    else
                        cmp "$expected" "$workspace/graph.generated.$suffix"
                    fi
                done
            done
        done
    done
done
