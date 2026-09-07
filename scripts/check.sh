#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    ''|--toolchain-only) ;;
    *) echo 'Usage: check.sh [--toolchain-only]' >&2; exit 2 ;;
esac
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
for script in scripts/*.sh; do bash -n "$script"; done
python3 - <<'CHECK'
import ast
import json
import os
import platform
import re
from pathlib import Path
from scripts.toolchain_pins import select
ast.parse(Path("scripts/setup.py").read_text())
pins = json.loads(Path("scripts/toolchains.json").read_text())
assert pins["dotnet"]["version"] == json.loads(Path("global.json").read_text())["sdk"]["version"]
assert pins["bazel"]["version"] == Path(".bazelversion").read_text().strip()
for machine in ('x86_64', 'aarch64'):
    for pin in select(pins, machine).values():
        assert re.fullmatch('[0-9a-f]{64}', pin['sha256'])
        assert pin['url'].startswith('https://')
if os.environ.get('SPIKE_CONTAINER_PREBUILT') == '1':
    selected = select(pins, platform.machine())
    stamps = {
        'dotnet': Path(os.environ['DOTNET_ROOT']).parent / 'dotnet.sha256',
        'bazel': Path(os.environ['SPIKE_BAZEL']).parents[1] / 'bazel.sha256',
    }
    for name, stamp in stamps.items():
        assert stamp.read_text().strip() == selected[name]['sha256'], f'Prebuilt {name} pin mismatch; rebuild the toolchain image'
CHECK
expected_dotnet="$(python3 -c 'import json; print(json.load(open("global.json"))["sdk"]["version"])')"
actual_dotnet="$(bash scripts/dotnet.sh --version)"
if [[ "$actual_dotnet" != "$expected_dotnet" ]]; then
    printf 'Expected .NET SDK %s, got %s.\n' "$expected_dotnet" "$actual_dotnet" >&2
    exit 1
fi
expected_bazel="bazel $(cat .bazelversion)"
actual_bazel="$(SPIKE_BAZEL_MODE=batch bash scripts/bazel.sh version --gnu_format)"
# Nixpkgs builds Bazel from the release archive with this exact label suffix.
if [[ "$actual_bazel" != "$expected_bazel" && "$actual_bazel" != "$expected_bazel- (@non-git)" ]]; then
    printf 'Expected %s, got %s.\n' "$expected_bazel" "$actual_bazel" >&2
    exit 1
fi
printf 'Environment checks passed (not an MSBuild/Bazel integration test).\n'
if [[ "${1:-}" == --toolchain-only ]]; then
    echo 'Toolchain-only check: repository Starlark validation is not included.'
else
    python3 scripts/check-starlark.py
fi
