#!/usr/bin/env bash
# Run inside the qualified Linux environment, with a freshly acquired pinned VMR.
set -euo pipefail
if [[ $# -ne 2 ]]; then
    echo 'Usage: baseline.sh SOURCE EVIDENCE_DIRECTORY' >&2
    exit 2
fi
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_root="$(cd -- "$1" && pwd)"
mkdir -p "$2"
evidence="$(cd -- "$2" && pwd)"
python3 "$here/inventory.py" "$source_root" "$evidence/inventory.json"
patch --directory "$source_root" -p1 --forward < "$here/patches/identitymodel-file-version.patch"
export DOTNET_PROCESSOR_COUNT=2
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
cd "$source_root"
dpkg-query -W > "$evidence/native-packages.tsv"
./prep-source-build.sh --bootstrap-rid linux-arm64 > "$evidence/preparation.log" 2>&1
/usr/bin/time -v -o "$evidence/build.time" \
    ./build.sh -sb --clean-while-building --configuration Release --arch arm64 --official-build-id 20251023.11 --branding rtm \
    --source-repository https://github.com/dotnet/dotnet \
    --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa \
    /p:BuildInParallel=false > "$evidence/build.log" 2>&1
