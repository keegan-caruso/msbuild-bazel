#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
case "$(uname -s):$(uname -m)" in
    Linux:x86_64|Linux:aarch64|Linux:arm64) ;;
    *) echo 'The bootstrap supports Linux x86-64 and ARM64 only.' >&2; exit 1 ;;
esac
for prerequisite in python3 curl tar; do
    command -v "$prerequisite" >/dev/null || { echo "Missing prerequisite: $prerequisite" >&2; exit 1; }
done
python3 scripts/setup.py
python3 scripts/setup-starlark.py
bash scripts/check.sh "$@"
