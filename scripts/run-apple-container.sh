#!/usr/bin/env bash
# Execute a repository command in a clean native Linux build environment.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo 'Requires Apple container on an Apple silicon Mac.' >&2; exit 1
fi
command -v container >/dev/null || { echo 'Install Apple container first.' >&2; exit 1; }
if [[ $# == 0 ]]; then echo 'Usage: bash scripts/run-apple-container.sh COMMAND [ARGS...]' >&2; exit 2; fi
arch="${RULES_MSBUILD_CONTAINER_ARCH:-arm64}"
image="${RULES_MSBUILD_CONTAINER_IMAGE:-ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc}"
case "$arch" in arm64|amd64) ;; *) echo 'RULES_MSBUILD_CONTAINER_ARCH must be arm64 or amd64.' >&2; exit 2 ;; esac
cache_url="${RULES_MSBUILD_SHARED_CACHE_URL:-}"
if [[ -n "$cache_url" && ( ! "$cache_url" =~ ^https?://[^[:space:]\"]+$ || "$cache_url" == *"'"* || "$cache_url" == *\\* || "$cache_url" == *'#'* ) ]]; then
    echo 'RULES_MSBUILD_SHARED_CACHE_URL must be an HTTP(S) URL without whitespace, quotes, backslashes or fragments.' >&2; exit 2
fi
relay_mount=()
if [[ -n "${RULES_MSBUILD_SHARED_CACHE_SOCKET:-}" ]]; then
    if [[ "$cache_url" != https://* || ! -S "$RULES_MSBUILD_SHARED_CACHE_SOCKET" ]]; then
        echo 'Shared cache relay requires an HTTPS URL and an existing host UNIX socket.' >&2; exit 2
    fi
    relay_mount=(--volume "$RULES_MSBUILD_SHARED_CACHE_SOCKET:/var/host-services/shared-cache.sock")
fi
mkdir -p "$repo_root/artifacts/apple-container"
run_dir="$(mktemp -d "$repo_root/artifacts/apple-container/run.XXXXXX")"
printf 'Container evidence: %s\n' "$run_dir"
container run --rm --init -i --arch "$arch" --cpus "${RULES_MSBUILD_CONTAINER_CPUS:-4}" --memory "${RULES_MSBUILD_CONTAINER_MEMORY:-6G}" \
    ${relay_mount[@]+"${relay_mount[@]}"} \
    -e "RULES_MSBUILD_SHARED_CACHE_RELAY=${RULES_MSBUILD_SHARED_CACHE_SOCKET:+1}" \
    -e "RULES_MSBUILD_SHARED_CACHE_URL=$cache_url" \
    -e "RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=${RULES_MSBUILD_PROJECT_CACHE_READ_ONLY:-0}" \
    -e "USE_BAZEL_VERSION=${USE_BAZEL_VERSION:-}" \
    -e "RULES_MSBUILD_CONTAINER_PREBUILT=${RULES_MSBUILD_CONTAINER_PREBUILT:-0}" \
    -e "RULES_MSBUILD_BAZEL_MODE=${RULES_MSBUILD_BAZEL_MODE:-server}" \
    --masked-path NONE --read-only-path NONE \
    -v "$repo_root:/src:ro" -v "$run_dir:/evidence" \
    "$image" \
    bash -s -- "$@" <<'GUEST' 2>&1 | tee "$run_dir/run.log"
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [[ "${RULES_MSBUILD_CONTAINER_PREBUILT:-0}" != 1 ]]; then
    apt-get update -qq
    apt-get install -y -qq python3 curl ca-certificates libicu70 libssl3 zlib1g git
fi
mkdir /workspace
tar -C /src --exclude=.git --exclude=.tools --exclude=.cache --exclude=artifacts \
    --exclude=bin --exclude=obj --exclude='./bazel-*' --exclude=__pycache__ -cf - . |
    tar -C /workspace -xf -
cd /workspace
if [[ "${RULES_MSBUILD_SHARED_CACHE_RELAY:-}" == 1 ]]; then
    python3 scripts/shared-cache-guest-relay.py --url "$RULES_MSBUILD_SHARED_CACHE_URL" \
        --socket /var/host-services/shared-cache.sock --ready /tmp/shared-cache-relay.ready &
    relay_pid=$!
    for attempt in {1..100}; do
        [[ -e /tmp/shared-cache-relay.ready ]] && break
        kill -0 "$relay_pid" 2>/dev/null || { wait "$relay_pid"; exit 1; }
        sleep 0.1
    done
    [[ -e /tmp/shared-cache-relay.ready ]] || { echo 'Shared cache relay startup timed out.' >&2; exit 1; }
fi
if [[ -n "${RULES_MSBUILD_SHARED_CACHE_URL:-}" ]]; then
    export RULES_MSBUILD_PROJECT_CACHE_URL="$RULES_MSBUILD_SHARED_CACHE_URL"
    # Guest-only defaults, including nested consumers using ordinary Bazel wrappers.
    # Command-line options can still override these for recovery controls.
    cat >> "$HOME/.bazelrc" <<CACHE
build --remote_cache=$RULES_MSBUILD_SHARED_CACHE_URL
build --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=$RULES_MSBUILD_SHARED_CACHE_URL
build --action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=${RULES_MSBUILD_PROJECT_CACHE_READ_ONLY:-0}
build --disk_cache=
build --remote_download_outputs=all
build --remote_cache_async=false
build --jobs=2
build --worker_max_instances=MSBuildGraph=1
test --local_test_jobs=1
CACHE
fi
if [[ "${RULES_MSBUILD_CONTAINER_PREBUILT:-0}" == 1 ]]; then
    echo 'Using prebuilt toolchain; checking repository pins.'
    bash scripts/tooling.sh setup-starlark
    bash scripts/check.sh
else
    bash scripts/setup.sh
fi
exec "$@"
GUEST
