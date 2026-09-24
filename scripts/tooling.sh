#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
bash "$REPO_ROOT/scripts/dotnet.sh" build "$REPO_ROOT/tools/Tooling/Tooling.csproj" --configuration Release --nologo >&2
exec "$DOTNET_ROOT/dotnet" "$REPO_ROOT/tools/Tooling/bin/Release/net10.0/Tooling.dll" "$REPO_ROOT" "$@"
