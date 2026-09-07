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
mkdir -p "$repo_root/artifacts/apple-container"
run_dir="$(mktemp -d "$repo_root/artifacts/apple-container/run.XXXXXX")"
printf 'Container evidence: %s\n' "$run_dir"
container run --rm --init -i --arch "$arch" --cpus "${RULES_MSBUILD_CONTAINER_CPUS:-4}" --memory "${RULES_MSBUILD_CONTAINER_MEMORY:-6G}" \
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
if [[ "${RULES_MSBUILD_CONTAINER_PREBUILT:-0}" == 1 ]]; then
    echo 'Using prebuilt toolchain; checking repository pins.'
    python3 scripts/setup-starlark.py
    bash scripts/check.sh
else
    bash scripts/setup.sh
fi
exec "$@"
GUEST
