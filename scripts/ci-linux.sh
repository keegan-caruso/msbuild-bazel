#!/usr/bin/env bash
# Setup tools first. Full runs quick before acceptance; CI invokes the phases separately.
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
    python3 -m unittest discover -s tests/preparation_reuse -v
    bash scripts/bazel.sh query //:repo_setup --noshow_progress
    bash scripts/check-dotnet.sh
    python3 -m unittest discover -s tests/e2e -p test_action_runner.py -v
    python3 -m unittest discover -s tests/graph -v
    bash scripts/bazel.sh test //tests/starlark:core //tests/starlark:extensions \
        --test_output=errors --nocache_test_results
fi
if [[ "$scope" != quick ]]; then
    # Runner contracts already ran in quick. Keep every other e2e module once.
    for test_file in tests/e2e/test_*.py; do
        [[ "$test_file" == tests/e2e/test_action_runner.py ]] && continue
        python3 -m unittest discover -s tests/e2e -p "${test_file##*/}" -v
    done
    for suite in graph_execution graph_handoff graph_cache multilanguage \
        graph_cache_full graph_packages configured_nodes configured_execution \
        lifecycle scale_synthetic scale_synthetic_native; do
        python3 -m unittest discover -s "tests/$suite" -v
    done
fi
