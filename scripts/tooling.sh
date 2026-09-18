#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
bash "$REPO_ROOT/scripts/dotnet.sh" build "$REPO_ROOT/tools/Preparation/Preparation.csproj" --configuration Release --nologo >&2
exec "$DOTNET_ROOT/dotnet" "$REPO_ROOT/tools/Preparation/bin/Release/net10.0/Preparation.dll" tooling "$REPO_ROOT" "$@"
