#!/usr/bin/env bash
# Serial JSON-lines controller; each request explicitly opts into store trust.
set -euo pipefail
workflow_nuget_packages="${NUGET_PACKAGES-}"
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
bash "$REPO_ROOT/scripts/dotnet.sh" build "$REPO_ROOT/tools/Preparation/Preparation.csproj" --configuration Release --nologo >&2
if [[ -n "$workflow_nuget_packages" ]]; then export NUGET_PACKAGES="$workflow_nuget_packages"; else unset NUGET_PACKAGES; fi
exec "$DOTNET_ROOT/dotnet" "$REPO_ROOT/tools/Preparation/bin/Release/net10.0/Preparation.dll" workflow-session
