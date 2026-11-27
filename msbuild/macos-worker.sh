#!/bin/bash
# One fresh macOS graph request. The broker keeps the write end of stdin.
set -euo pipefail
[[ $(uname -sm) == 'Darwin arm64' && $6 == Build && $7 == action && $8 == - ]] || {
    echo 'macos_worker requires macOS ARM64 and an ordinary Build' >&2; exit 1;
}
sdk=$(dirname "$(realpath "$1/dotnet")")
runner=$(dirname "$(realpath "$2/GraphBuild.dll")")
output=$(realpath "$3")
contract=$(realpath "$4")
scratch=$(realpath "$5")
mkdir -p "$scratch/tmp" "$scratch/.local/share"
cd "$output/workspace"
profile='
(version 1)
(deny default)
(import "system.sb")
(allow process*)
(allow signal (target self))
(allow sysctl-read)
(allow file-read-metadata)
(allow file-read* file-map-executable
    (subpath "/bin") (subpath "/usr/bin") (subpath "/usr/share")
    (subpath (param "SDK")) (subpath (param "RUNNER")))
(allow file-read* (subpath "/private/etc") (literal "/dev/random") (literal "/dev/urandom")
    (literal (param "CONTRACT")))
(allow file-read* file-write* (literal "/dev/null") (subpath (param "SCRATCH")) (subpath (param "OUTPUT")))
'
# Keep the child in its own process group. EOF on the broker pipe also covers an
# abrupt broker exit while a task or one of its descendants is still running.
set -m
exec 3<&0
/usr/bin/env -i PATH=/usr/bin:/bin HOME="$scratch" TMPDIR="$scratch/tmp" \
    DOTNET_ROOT="$sdk" DOTNET_CLI_HOME="$scratch" DOTNET_EnableDiagnostics=0 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1 \
    MSBUILDDISABLENODEREUSE=1 DOTNET_CLI_USE_MSBUILD_SERVER=false MSBUILDUSESERVER=0 \
    RULES_MSBUILD_GRAPH_SINGLE_NODE=1 RULES_MSBUILD_GRAPH_PROFILE="${11:-0}" \
    /usr/bin/sandbox-exec -D SDK="$sdk" -D RUNNER="$runner" -D CONTRACT="$contract" \
    -D OUTPUT="$output" -D SCRATCH="$scratch" -p "$profile" \
    "$sdk/dotnet" exec "$runner/GraphBuild.dll" action "$PWD" "$contract" \
    "$output/report.json" "$scratch/cache" Build </dev/null 3<&- &
child=$!
(IFS= read -r _ <&3 || :; kill -KILL -- "-$child" 2>/dev/null || :) &
monitor=$!
trap 'kill "$monitor" 2>/dev/null || :; wait "$monitor" 2>/dev/null || :' EXIT
wait "$child"
