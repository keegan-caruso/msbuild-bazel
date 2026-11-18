#!/usr/bin/env bash
# Run inside the qualified Linux environment, with a freshly acquired pinned VMR.
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
    echo 'Usage: baseline.sh SOURCE EVIDENCE_DIRECTORY [X64_ACQUISITION_DIRECTORY]' >&2
    exit 2
fi
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(cd -- "$1" && pwd)"
mkdir -p "$2"
evidence="$(cd -- "$2" && pwd)"
architecture="${RULES_MSBUILD_SOURCE_SDK_ARCH:-arm64}"
case "$architecture:$(uname -s):$(uname -m)" in
    arm64:Linux:aarch64|x64:Linux:x86_64) ;;
    *) echo 'Source SDK baseline requires the selected native Linux architecture' >&2; exit 2 ;;
esac
python3 "$here/inventory.py" "$source_root" "$evidence/inventory.json" --architecture="$architecture"
patch --directory "$source_root" -p1 --forward < "$here/patches/identitymodel-file-version.patch"
export DOTNET_PROCESSOR_COUNT=2
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
if [[ "$architecture" == x64 ]]; then
    [[ $# -eq 3 ]] || { echo 'x64 baseline requires the pinned acquisition directory' >&2; exit 2; }
    acquisition="$(cd -- "$3" && pwd)"
    python3 "$here/acquire_x64.py" "$acquisition" --verify
    [[ ! -e "$source_root/.dotnet" ]] || { echo 'Use a fresh source tree for x64 bootstrap staging' >&2; exit 2; }
    mkdir "$source_root/.dotnet"
    tar -xzf "$acquisition/dotnet-sdk-10.0.100-rc.2.25502.107-linux-x64.tar.gz" -C "$source_root/.dotnet"
    mkdir -p "$source_root/prereqs/packages/archive"
    cp "$acquisition/Private.SourceBuilt.Artifacts.10.0.100-rc.2.25502.107.centos.10-x64.tar.gz" "$source_root/prereqs/packages/archive/"
    python3 "$here/prepare_x64_bootstrap.py" "$source_root" > "$evidence/bootstrap-inputs.log" 2>&1
fi
cd "$source_root"
dpkg-query -W > "$evidence/native-packages.tsv"
./prep-source-build.sh --bootstrap-rid "linux-$architecture" > "$evidence/preparation.log" 2>&1
/usr/bin/time -v -o "$evidence/build.time" \
    ./build.sh -sb --clean-while-building --configuration Release --arch "$architecture" --official-build-id 20251023.11 --branding rtm \
    --source-repository https://github.com/dotnet/dotnet \
    --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa \
    /p:BuildInParallel=false > "$evidence/build.log" 2>&1
