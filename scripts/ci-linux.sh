#!/usr/bin/env bash
# Setup tools first. Full runs quick before acceptance; CI invokes phases separately.
set -euo pipefail
case "${1:-quick}" in
    quick|acceptance|full) scope="${1:-quick}" ;;
    *) echo 'Usage: ci-linux.sh [quick|acceptance|full]' >&2; exit 2 ;;
esac
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if [[ "$scope" != acceptance ]]; then
    git diff --check
    python3 -m unittest discover -s tests/ci -v
    python3 -m unittest discover -s tests/bootstrap -v
    python3 -m unittest discover -s tests/benchmarks -v
    bash scripts/check-analysis.sh
    bash scripts/check-dotnet.sh
    python3 -m unittest discover -s tests/sdk_repository -v
fi
if [[ "$scope" != quick ]]; then
    source scripts/env.sh
    export RULES_MSBUILD_DOTNET_ROOT="$DOTNET_ROOT"
    evidence="$(mktemp -d "${TMPDIR:-/tmp}/msbuild-explicit-ci.XXXXXX")"
    echo "Explicit acceptance evidence: $evidence"
    python3 tests/explicit_msbuild/acceptance.py "$evidence/acceptance"
fi
