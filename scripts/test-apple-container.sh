#!/usr/bin/env bash
# Run a clean Shared -> App smoke test without writing into the source fixture.
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    echo 'This smoke test requires Apple container on an Apple silicon Mac.' >&2
    exit 1
fi
command -v container >/dev/null || { echo 'Install Apple container first.' >&2; exit 1; }

image="${SPIKE_CONTAINER_IMAGE:-ubuntu@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc}"
arch="${SPIKE_CONTAINER_ARCH:-arm64}"
case "$arch" in arm64|amd64) ;; *) echo 'SPIKE_CONTAINER_ARCH must be arm64 or amd64.' >&2; exit 2 ;; esac
mkdir -p "$repo_root/artifacts/apple-container"
run_dir="$(mktemp -d "$repo_root/artifacts/apple-container/smoke.XXXXXX")"
printf 'Smoke-test log: %s/run.log\n' "$run_dir"

# Only this mount is shared with the guest; all generated files stay in its disk.
# Default guest path protections are sufficient for this MSBuild-only test.
container run --rm -i --arch "$arch" --cpus 2 --memory 2G \
    -v "$repo_root:/src:ro" "$image" bash -s <<'GUEST' 2>&1 | tee "$run_dir/run.log"
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [[ "${SPIKE_CONTAINER_PREBUILT:-0}" != 1 ]]; then
    apt-get update -qq
    apt-get install -y -qq python3 curl ca-certificates libicu70 libssl3 zlib1g
fi

mkdir -p /workspace/fixture
cp -a /src/scripts /src/global.json /src/.bazelversion /workspace/
cp -a /src/tests/fixtures/two-projects/. /workspace/fixture/
cd /workspace
if [[ "${SPIKE_CONTAINER_PREBUILT:-0}" == 1 ]]; then
    echo 'Using prebuilt toolchain; checking repository pins.'
    bash scripts/check.sh --toolchain-only
else
    bash scripts/setup.sh --toolchain-only
fi
source scripts/env.sh
cd /workspace/fixture

"$DOTNET_ROOT/dotnet" msbuild dirs.proj -t:Restore -p:Configuration=Release -nologo
"$DOTNET_ROOT/dotnet" msbuild dirs.proj -t:Build -p:Configuration=Release \
    -graphBuild -isolateProjects -nologo
actual="$("$DOTNET_ROOT/dotnet" App/bin/Release/net10.0/App.dll)"
if [[ "$actual" != 'shared-v1/app-v1' ]]; then
    printf 'FAIL: expected shared-v1/app-v1, got: %s\n' "$actual" >&2
    exit 1
fi
printf 'PASS: Shared -> App produced %s\n' "$actual"
GUEST
