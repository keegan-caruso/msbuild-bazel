#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
for script in scripts/*.sh; do bash -n "$script"; done
python3 - <<'CHECK'
import ast
import json
from pathlib import Path
ast.parse(Path("scripts/setup.py").read_text())
pins = json.loads(Path("scripts/toolchains.json").read_text())
assert pins["dotnet"]["version"] == json.loads(Path("global.json").read_text())["sdk"]["version"]
assert pins["bazel"]["version"] == Path(".bazelversion").read_text().strip()
CHECK
expected_dotnet="$(python3 -c 'import json; print(json.load(open("global.json"))["sdk"]["version"])')"
actual_dotnet="$(bash scripts/dotnet.sh --version)"
if [[ "$actual_dotnet" != "$expected_dotnet" ]]; then
    printf 'Expected .NET SDK %s, got %s.\n' "$expected_dotnet" "$actual_dotnet" >&2
    exit 1
fi
expected_bazel="bazel $(cat .bazelversion)"
actual_bazel="$(bash scripts/bazel.sh version --gnu_format)"
# Nixpkgs builds Bazel from the release archive with this exact label suffix.
if [[ "$actual_bazel" != "$expected_bazel" && "$actual_bazel" != "$expected_bazel- (@non-git)" ]]; then
    printf 'Expected %s, got %s.\n' "$expected_bazel" "$actual_bazel" >&2
    exit 1
fi
printf 'Environment checks passed (not an MSBuild/Bazel integration test).\n'
