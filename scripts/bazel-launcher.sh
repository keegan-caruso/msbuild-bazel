#!/usr/bin/env bash
# Preserve the caller's workspace while selecting this repository's Bazel version.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
if [[ ! -x "$RULES_MSBUILD_BAZELISK" ]]; then
    echo 'Run bash scripts/setup.sh or enter nix develop first.' >&2
    exit 1
fi
exec "$RULES_MSBUILD_BAZELISK" "$@"
