#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
case "$SDK_TEST_RID" in
    win-*)
        export MSYS2_ARG_CONV_EXCL='//;@'
        sed -i "/global_json = /a\    platforms = [\"$SDK_TEST_RID\"]," MODULE.bazel
        ;;
esac
bazel run //:sync -- --check
bazel run //:app > "$TEST_TMPDIR/app.log"
assert_contains "$TEST_TMPDIR/app.log" 'Hello from MSBuild and Bazel'
bazel test //:tests --test_output=errors
bazel run //:sync -- --check
echo 'PASS: committed quickstart sync/check, run and test'
