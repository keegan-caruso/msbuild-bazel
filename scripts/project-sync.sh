#!/usr/bin/env bash
# Evaluate locally during synchronization; ordinary Bazel builds do not call this.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
if [[ $# -lt 2 ]]; then
    echo 'Usage: project-sync.sh /absolute/workspace project.csproj... [--check]' >&2
    exit 2
fi
cd "$REPO_ROOT"
version="$("$DOTNET_ROOT/dotnet" --version)"
sdk="$DOTNET_ROOT/sdk/$version"
bash "$REPO_ROOT/scripts/dotnet.sh" build "$REPO_ROOT/tools/ProjectSync/ProjectSync.csproj" --configuration Release --nologo >&2
exec "$DOTNET_ROOT/dotnet" "$REPO_ROOT/tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll" "$1" "$sdk" "${@:2}"
