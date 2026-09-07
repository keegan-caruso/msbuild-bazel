#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ ! -x "$SPIKE_BAZEL" ]]; then
    echo 'Enter nix develop or run bash scripts/setup.sh first.' >&2
    exit 1
fi
case "${SPIKE_BAZEL_MODE:-server}" in
    server) startup=(--max_idle_secs=120) ;;
    batch) startup=(--batch) ;;
    *) echo 'SPIKE_BAZEL_MODE must be batch or server.' >&2; exit 2 ;;
esac
exec "$SPIKE_BAZEL" "${startup[@]}" --output_user_root="$REPO_ROOT/.cache/bazel" "$@"
