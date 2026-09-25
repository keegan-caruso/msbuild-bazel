#!/usr/bin/env bash
# Build only repository-owned tooling and unit tests; fixture builds retain their own policy.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
case "${1:-}" in
    '') projects=(tools/Tooling/Tooling.csproj tools/ExplicitBuild/ExplicitBuild.csproj tools/ProjectSync/ProjectSync.csproj) ;;
    *) echo 'Usage: check-dotnet.sh' >&2; exit 2 ;;
esac
for project in "${projects[@]}"; do
    bash scripts/dotnet.sh build "$project" --configuration Release --no-incremental -warnaserror
    bash scripts/dotnet.sh format "$project" --verify-no-changes --no-restore \
        --severity warn
done
python3 -m unittest discover -s tests/code_style -v
python3 -m unittest discover -s tests/tooling -v

python3 -m unittest discover -s tests/explicit_msbuild -v

python3 -m unittest discover -s tests/project_sync -v
