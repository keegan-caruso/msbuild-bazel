#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    ''|--toolchain-only) ;;
    *) echo 'Usage: check.sh [--toolchain-only]' >&2; exit 2 ;;
esac
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
for script in scripts/*.sh; do bash -n "$script"; done
bash scripts/tooling.sh check "${1:-}"
