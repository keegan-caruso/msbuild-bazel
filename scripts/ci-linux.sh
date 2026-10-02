#!/usr/bin/env bash
# Setup tools first. Full runs quick before acceptance; CI invokes phases separately.
set -euo pipefail
case "${1:-quick}" in
    quick|acceptance|full) scope="${1:-quick}" ;;
    *) echo 'Usage: ci-linux.sh [quick|acceptance|full]' >&2; exit 2 ;;
esac
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
source scripts/validation.sh
if [[ "$scope" != acceptance ]]; then
    run_validation_phase common
    run_validation_phase version
fi
if [[ "$scope" != quick ]]; then
    evidence="$(mktemp -d "${TMPDIR:-/tmp}/msbuild-graph-ci.XXXXXX")"
    echo "Graph acceptance evidence: $evidence"
    run_validation_phase acceptance "$evidence/acceptance"
fi
