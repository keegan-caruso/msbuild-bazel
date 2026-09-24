#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ ! -x "$DOTNET_ROOT/dotnet" ]]; then
    echo 'Enter nix develop or run bash scripts/setup.sh first.' >&2
    exit 1
fi
exec "$DOTNET_ROOT/dotnet" "$@"
