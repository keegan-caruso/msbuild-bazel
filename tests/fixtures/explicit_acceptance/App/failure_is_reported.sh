#!/usr/bin/env bash
set -euo pipefail

log="$TEST_TMPDIR/failure.log"
if XML_OUTPUT_FILE="$TEST_TMPDIR/inner-test.xml" "$TEST_SRCDIR/$TEST_WORKSPACE/App/Fails" fail >"$log" 2>&1; then
    echo "Expected the executable test to fail" >&2
    exit 1
fi
grep -q '7:resource:runtime' "$log"
