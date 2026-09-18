#!/usr/bin/env bash
# Build and invoke the .NET fresh-preparation controller; no Python dependency.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
bash "$REPO_ROOT/scripts/dotnet.sh" build "$REPO_ROOT/tools/Preparation/Preparation.csproj" --configuration Release --nologo >&2
exec "$DOTNET_ROOT/dotnet" "$REPO_ROOT/tools/Preparation/bin/Release/net10.0/Preparation.dll" prepare "$@"
