#!/usr/bin/env bash
# Shared phases for local checks, the version matrix, and manual Linux CI.
set -euo pipefail

run_validation_phase() {
    local phase="${1:-}" evidence="${2:-}"
    case "$phase" in
        common)
            git diff --check
            python3 -m unittest discover -s tests/ci -v
            python3 -m unittest discover -s tests/bootstrap -v
            python3 -m unittest discover -s tests/benchmarks -v
            bash scripts/check-dotnet.sh
            ;;
        version)
            bash scripts/check.sh
            bash scripts/check-analysis.sh
            python3 -m unittest discover -s tests/sdk_repository -v
            ;;
        acceptance)
            if [[ -z "$evidence" ]]; then
                echo 'Acceptance requires a fresh evidence directory.' >&2
                return 2
            fi
            python3 tests/explicit_msbuild/acceptance.py "$evidence"
            ;;
        *) echo 'Usage: validation.sh common|version|acceptance [evidence-directory]' >&2; return 2 ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
    cd "$REPO_ROOT"
    run_validation_phase "$@"
fi
