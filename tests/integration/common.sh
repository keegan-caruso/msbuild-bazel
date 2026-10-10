#!/usr/bin/env bash
# Sourced by integration runners. Only declared runfiles enter the scratch tree.
set -euo pipefail
case "$(uname -s)/$(uname -m)" in
    Linux/aarch64) export SDK_TEST_RID=linux-arm64 ;;
    Linux/x86_64) export SDK_TEST_RID=linux-x64 ;;
    Darwin/arm64) export SDK_TEST_RID=osx-arm64 ;;
    Darwin/x86_64) export SDK_TEST_RID=osx-x64 ;;
    *) echo 'Integration fixtures require macOS or Linux ARM64/x64.' >&2; exit 1 ;;
esac
# TEST_TMPDIR is nested below the rules checkout's execroot. MSBuild would discover
# its ancestor .editorconfig there, so put consumer sources outside that tree.
scratch=$(mktemp -d /tmp/msbuild-bazel-integration.XXXXXX)
mkdir -p "$scratch/consumer" "$scratch/msbuild-bazel"
cp -RL "$BIT_WORKSPACE_DIR/." "$scratch/consumer/"
tar -xf "$RULES_ARCHIVE" -C "$scratch/msbuild-bazel"
if [[ -n "$(find "$scratch/msbuild-bazel" -type l -print -quit)" ]]; then
    echo 'Rules archive must contain independent files, not checkout symlinks.' >&2
    rm -rf "$scratch"
    exit 1
fi
# Keep the public example's ../msbuild-bazel override unchanged.
cd "$scratch/consumer"
unset RULES_MSBUILD_PROJECT_CACHE_URL RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN
# Nested builds own a separate server and output base; always stop it on exit.
bazel() {
    # macOS ships Bash 3.2, where an empty array is unset under set -u.
    local args=(--nosystem_rc --nohome_rc --noworkspace_rc "--output_base=$scratch/bazel" "$1")
    case "$1" in
        build|run|test)
            if [[ -n "${RULES_MSBUILD_TEST_REPOSITORY_CACHE:-}" ]]; then
                args+=("--repository_cache=$RULES_MSBUILD_TEST_REPOSITORY_CACHE")
            fi ;;
    esac
    "$BIT_BAZEL_BINARY" "${args[@]}" "${@:2}"
}
cleanup() {
    bazel shutdown >/dev/null 2>&1 || true
    # Bazel publishes read-only output directories. Make only our scratch
    # directories writable; find does not follow external/toolchain symlinks.
    find "$scratch" -type d -exec chmod u+w {} +
    rm -rf "$scratch"
}
trap cleanup EXIT
assert_contains() {
    if ! grep -Fq -- "$2" "$1"; then cat "$1" >&2; echo "Missing: $2" >&2; exit 1; fi
}
