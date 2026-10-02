#!/usr/bin/env bash
# Read-only graph inputs; only diagnostic reports and temporary scratch are writable.
set -euo pipefail
sdk=$(realpath "$1"); runner=$(realpath "$2"); workspace=$(realpath "$3")
prepared=$(realpath "$4"); contract=$(realpath "$5"); probe=$(realpath "$6"); results=$(realpath "$7")
base=/__rules_msbuild_graph
args=(--die-with-parent --unshare-user --unshare-pid --unshare-ipc --unshare-uts
      --new-session --cap-drop ALL --clearenv --proc /proc --dev /dev --tmpfs /tmp)
for path in /usr /bin /lib /lib64 /etc/ld.so.cache /etc/os-release /etc/passwd /etc/group /etc/ssl/certs /etc/resolv.conf /etc/hosts /etc/nsswitch.conf; do
    if [[ -e $path ]]; then args+=(--ro-bind "$path" "$path"); fi
done
args+=(--ro-bind "$sdk" "$base/sdk" --ro-bind "$runner" "$base/runner"
       --ro-bind "$workspace" "$base/output/workspace"
       --ro-bind "$prepared/.nuget" "$base/output/workspace/.nuget"
       --ro-bind "$prepared/manifest.json" "$base/prepared-manifest.json"
       --ro-bind "$contract" "$base/contract.json" --ro-bind "$probe" "$base/probe"
       --bind "$results" "$base/results" --tmpfs "$base/scratch" --chdir "$base/output/workspace")
for pair in "DOTNET_ROOT=$base/sdk" "DOTNET_HOST_PATH=$base/sdk/dotnet" \
    "NUGET_PACKAGES=$base/output/workspace/.nuget" "HOME=$base/scratch" "DOTNET_CLI_HOME=$base/scratch" \
    'PATH=/usr/bin:/bin' 'TMPDIR=/tmp' 'LANG=C.UTF-8' 'TZ=UTC' \
    'DOTNET_CLI_TELEMETRY_OPTOUT=1' 'DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1' 'DOTNET_NOLOGO=1' \
    'MSBUILDDISABLENODEREUSE=1'; do
    args+=(--setenv "${pair%%=*}" "${pair#*=}")
done
exec /usr/bin/bwrap "${args[@]}" -- "$base/sdk/dotnet" "$base/probe/Probe.dll" \
    "$base/runner/GraphBuild.dll" "$base/output/workspace" "$base/contract.json" "$base/sdk" \
    "$base/results/$8.json" "$9" "$base/prepared-manifest.json"
