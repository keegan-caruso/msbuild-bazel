#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ ! -x "$RULES_MSBUILD_BAZEL" ]]; then
    echo 'Enter nix develop or run bash scripts/setup.sh first.' >&2
    exit 1
fi
case "${RULES_MSBUILD_BAZEL_MODE:-server}" in
    server) startup=(--max_idle_secs=120) ;;
    batch) startup=(--batch) ;;
    *) echo 'RULES_MSBUILD_BAZEL_MODE must be batch or server.' >&2; exit 2 ;;
esac
exec "$RULES_MSBUILD_BAZEL" "${startup[@]}" "$@"
