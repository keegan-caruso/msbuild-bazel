#!/usr/bin/env bash
# SDK-free rule contracts, plus action metadata unavailable to analysis tests.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
bash scripts/bazel.sh test //tests/analysis/... --test_output=errors --lockfile_mode=off
python3 tests/analysis/execution_requirements.py
