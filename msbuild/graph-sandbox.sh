#!/usr/bin/env bash
# Fixed paths for a single graph action. Network remains available for cache IO.
set -euo pipefail
if [[ $(uname -s) != Linux || ! -x /usr/bin/bwrap ]]; then
    echo 'linux_stable_paths requires Linux and /usr/bin/bwrap' >&2
    exit 1
fi
sdk=$(dirname "$(realpath "$1/dotnet")"); runner=$(dirname "$(realpath "$2/GraphBuild.dll")"); output=$(realpath "$3")
contract=$(realpath "$4"); scratch=$(realpath "$5"); target=$6
base=/__rules_msbuild_graph
args=(--die-with-parent --unshare-user --unshare-ipc --unshare-uts
      --new-session --cap-drop ALL --clearenv --ro-bind /proc /proc --dev /dev --tmpfs /tmp)
for path in /usr /bin /lib /lib64 /etc/ld.so.cache /etc/os-release /etc/passwd /etc/group /etc/ssl/certs /etc/resolv.conf /etc/hosts /etc/nsswitch.conf; do
    if [[ -e $path ]]; then args+=(--ro-bind "$path" "$path"); fi
done
args+=(--ro-bind "$sdk" "$base/sdk" --ro-bind "$runner" "$base/runner"
       --ro-bind "$contract" "$base/contract.json" --bind "$output" "$base/output"
       --bind "$scratch" "$base/scratch" --chdir "$base/output/workspace")
for pair in "DOTNET_ROOT=$base/sdk" "HOME=$base/scratch" "DOTNET_CLI_HOME=$base/scratch" \
    'PATH=/usr/bin:/bin' 'TMPDIR=/tmp' 'LANG=C.UTF-8' 'TZ=UTC' \
    'DOTNET_CLI_TELEMETRY_OPTOUT=1' 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1' 'DOTNET_NOLOGO=1' \
    'MSBUILDDISABLENODEREUSE=1'; do
    args+=(--setenv "${pair%%=*}" "${pair#*=}")
done
for key in RULES_MSBUILD_PROJECT_CACHE_URL RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN; do
    if value=$(printenv "$key"); then args+=(--setenv "$key" "$value"); fi
done
exec /usr/bin/bwrap "${args[@]}" -- "$base/sdk/dotnet" exec "$base/runner/GraphBuild.dll" \
    action "$base/output/workspace" "$base/contract.json" "$base/output/report.json" "$base/scratch/cache" "$target"
