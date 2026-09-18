#!/usr/bin/env bash
# Build only repository-owned tooling and unit tests; fixture builds retain their own policy.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
for project in tools/*/*.csproj tests/ActionRunner.Tests/*.csproj tests/Preparation.Tests/*.csproj; do
    bash scripts/dotnet.sh build "$project" --configuration Release --no-incremental -warnaserror
    bash scripts/dotnet.sh format "$project" --verify-no-changes --no-restore \
        --diagnostics IDE0040 IDE0044 IDE0055 IDE0065 IDE0161 --severity warn
done
python3 -m unittest discover -s tests/code_style -v
python3 -m unittest discover -s tests/dotnet_preparation -v
python3 -m unittest discover -s tests/dotnet_workflow -v
