#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
    echo 'The initial bootstrap supports Linux x86-64 only.' >&2
    exit 1
fi
for prerequisite in python3 curl tar; do
    command -v "$prerequisite" >/dev/null || { echo "Missing prerequisite: $prerequisite" >&2; exit 1; }
done
python3 scripts/setup.py
bash scripts/check.sh
