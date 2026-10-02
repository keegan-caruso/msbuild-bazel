#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
bazel run //:sync -- --check
bazel run //:app > "$TEST_TMPDIR/app.log"
assert_contains "$TEST_TMPDIR/app.log" 'Hello from MSBuild and Bazel'
bazel test //:tests --test_output=errors
bazel run //:sync -- --check
echo 'PASS: committed quickstart sync/check, run and test'
