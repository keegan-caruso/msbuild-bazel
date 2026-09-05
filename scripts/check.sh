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
[[ "$(bash scripts/dotnet.sh --version)" == "$expected_dotnet" ]]
[[ "$(bash scripts/bazel.sh version --gnu_format)" == "bazel $(cat .bazelversion)" ]]
printf 'Environment checks passed (not an MSBuild/Bazel integration test).\n'
