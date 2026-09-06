#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ ! -x "$SPIKE_BAZEL" ]]; then
    echo 'Enter nix develop or run bash scripts/setup.sh first.' >&2
    exit 1
fi
exec "$SPIKE_BAZEL" --batch --output_user_root="$REPO_ROOT/.cache/bazel" "$@"
