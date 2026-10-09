#!/usr/bin/env bash
# Host SDK controls use the public workflow, without Linux namespaces/workers.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
case "$SDK_TEST_RID" in
    *-arm64) expected_arch=Arm64 ;;
    *-x64) expected_arch=X64 ;;
esac
options=(--disk_cache= --remote_cache=)
bazel run //:sync -- --check
run() {
    bazel run "//:$1" "${options[@]}" -- --smoke > "$TEST_TMPDIR/$2.log" 2>&1 || { cat "$TEST_TMPDIR/$2.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$2.log" "HTTP: $3"
    assert_contains "$TEST_TMPDIR/$2.log" "ARCH: $expected_arch"
}
checks() {
    bazel test //:tests //:web_test //:published_test "${options[@]}" --test_output=all > "$TEST_TMPDIR/$1-tests.log" 2>&1 || { cat "$TEST_TMPDIR/$1-tests.log" >&2; exit 1; }
    assert_contains "$TEST_TMPDIR/$1-tests.log" "UNIT: $2"
}
reference() {
    python3 - <<'PY'
import hashlib
from pathlib import Path
print(hashlib.sha256(Path('bazel-bin/build.graph/workspace/Data/obj/Release/net10.0/ref/Data.dll').read_bytes()).hexdigest())
PY
}
run app seed warehouse-v1
run published_app seed-publish warehouse-v1
checks seed warehouse-v1
before=$(reference)
python3 - <<'PY'
from pathlib import Path
p=Path('Data/CatalogStore.cs');p.write_text(p.read_text().replace('warehouse-v1','warehouse-v2'))
PY
run app body warehouse-v2
[[ $(reference) == "$before" ]]
checks body warehouse-v2
python3 - <<'PY'
from pathlib import Path
p=Path('Data/CatalogStore.cs');p.write_text(p.read_text().replace('    public static string Revision()', '    public static int ApiVersion() => 2;\n    public static string Revision()'))
PY
run app api warehouse-v2
[[ $(reference) != "$before" ]]
checks api warehouse-v2
run published_app edited-publish warehouse-v2
# The public contract remains current after source-body/API edits.
bazel run //:sync -- --check
bazel shutdown
mkdir "$scratch/recovery"
tar -cf "$scratch/consumer.tar" Domain Data Services Web Tests MODULE.bazel MODULE.bazel.lock BUILD.bazel global.json NuGet.Config Directory.Build.props mappings.json packages.bzl graph.generated.json graph.generated.bzl
tar -xf "$scratch/consumer.tar" -C "$scratch/recovery"
cd "$scratch/recovery"
# Strict locked acquisition in an independent output base; remote actions disabled.
"$BIT_BAZEL_BINARY" --batch --ignore_all_rc_files --output_base="$scratch/native-recovery" test //:tests //:published_test \
    "${options[@]}" --lockfile_mode=error --test_output=all \
    --repository_cache="${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-$scratch/repository-cache}" > "$TEST_TMPDIR/recovery.log" 2>&1 || { cat "$TEST_TMPDIR/recovery.log" >&2; exit 1; }
assert_contains "$TEST_TMPDIR/recovery.log" 'UNIT: warehouse-v2'
assert_contains "$TEST_TMPDIR/recovery.log" "HTTP: warehouse-v2"
assert_contains "$TEST_TMPDIR/recovery.log" "ARCH: $expected_arch"
echo "PASS: $SDK_TEST_RID downloaded SDK, packages, Razor/Publish, body/API edits and strict independent consumer"
