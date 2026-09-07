#!/usr/bin/env bash
# Run selected suites through the common disposable Linux environment.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# == 0 ]]; then set -- graph graph-execution e2e; fi
for suite in "$@"; do
    case "$suite" in graph|graph-execution|e2e) ;; *) echo "Unknown suite: $suite" >&2; exit 2 ;; esac
done
exec bash "$repo_root/scripts/run-apple-container.sh" python3 tools/run_container_suites.py --output /evidence "$@"
