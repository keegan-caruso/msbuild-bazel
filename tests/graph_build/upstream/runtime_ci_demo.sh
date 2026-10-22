#!/usr/bin/env bash
# Requires a relocated, qualified runtime-suites workspace and a stopped producer.
set -euo pipefail
if (( $# < 5 )); then
    echo "Usage: $0 WORKSPACE SEED_REPORT FRESH_DEMO_DIRECTORY CACHE_URL HOST_SPACE_BIND [--body-edit]" >&2
    exit 2
fi
workspace="$1"
seed_report="$2"
demo_directory="$3"
cache_url="$4"
host_space_bind="$5"
shift 5
if [[ "$demo_directory" != /* || -e "$demo_directory" ]]; then
    echo 'The demo directory must be absolute and must not exist.' >&2
    exit 2
fi
exec python3 "$(dirname -- "${BASH_SOURCE[0]}")/runtime_recovered_tests.py" \
    "$workspace" "$demo_directory/results" --output-base="$demo_directory/bazel" \
    --phase=consumer --seed-report="$seed_report" --cache-url="$cache_url" \
    --host-space-path="$host_space_bind" --demo --discard-output-base "$@"
