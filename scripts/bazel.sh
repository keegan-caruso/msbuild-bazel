#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ ! -x "$REPO_ROOT/.tools/bin/bazel" ]]; then
    echo 'Run bash scripts/setup.sh first.' >&2
    exit 1
fi
exec "$REPO_ROOT/.tools/bin/bazel" --batch --output_user_root="$REPO_ROOT/.cache/bazel" "$@"
