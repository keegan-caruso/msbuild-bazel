#!/usr/bin/env bash
# Build locally, then record the immutable digest used by subsequent runs.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
arch="${RULES_MSBUILD_CONTAINER_ARCH:-arm64}"
case "$arch" in arm64|amd64) ;; *) echo 'RULES_MSBUILD_CONTAINER_ARCH must be arm64 or amd64.' >&2; exit 2 ;; esac
command -v container >/dev/null || { echo 'Install Apple container first.' >&2; exit 1; }
context_dir="$(mktemp -d "${TMPDIR:-/tmp}/msbuild-toolchain.XXXXXX")"
trap 'rm -rf "$context_dir"' EXIT
mkdir "$context_dir/scripts"
cp "$repo_root/containers/toolchain.Dockerfile" "$context_dir/Dockerfile"
cp "$repo_root/global.json" "$repo_root/.bazelversion" "$context_dir/"
for name in setup.sh setup.py toolchain_pins.py toolchains.json env.sh check.sh dotnet.sh bazel.sh setup-starlark.py check-starlark.py starlark-tools.json; do
    cp "$repo_root/scripts/$name" "$context_dir/scripts/"
done
image_dir="$repo_root/.cache/apple-container/$arch"
mkdir -p "$image_dir"
tag="rules_msbuild-toolchain:$arch"
container build --platform "linux/$arch" --cpus 4 --memory 4G --tag "$tag" \
    "$context_dir" 2>&1 | tee "$image_dir/build.log"
container image inspect "$tag" > "$image_dir/image.json"
python3 - "$image_dir" "$context_dir" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
output, context = map(Path, sys.argv[1:])
config = json.loads((output / 'image.json').read_text())[0]['configuration']
reference = config['name'].rsplit(':', 1)[0] + '@' + config['descriptor']['digest']
(output / 'image.ref').write_text(reference + '\n')
(output / 'inputs.json').write_text(json.dumps({p.relative_to(context).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in sorted(context.rglob('*')) if p.is_file()}, indent=2) + '\n')
print('Pinned image:', reference)
print('Reference file:', output / 'image.ref')
PY

# Register the digest reference in Apple container's local image store.
container image tag "$tag" "$(cat "$image_dir/image.ref")"
