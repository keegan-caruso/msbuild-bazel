#!/usr/bin/env bash
# Build only repository-owned tooling and unit tests; fixture builds retain their own policy.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
source "$repo_root/scripts/env.sh"
case "${1:-}" in
    '') projects=(tools/Tooling/Tooling.csproj tools/ArtifactTools/ArtifactTools.csproj tools/ProjectSync/ProjectSync.csproj tools/GraphBuild/GraphBuild.csproj) ;;
    *) echo 'Usage: check-dotnet.sh' >&2; exit 2 ;;
esac
for project in "${projects[@]}"; do
    bash scripts/dotnet.sh build "$project" --configuration Release --no-incremental -warnaserror
    bash scripts/dotnet.sh format "$project" --verify-no-changes --no-restore \
        --severity warn
done
"${RULES_MSBUILD_PYTHON:-python3}" -m unittest discover -s tests/code_style -v
"${RULES_MSBUILD_PYTHON:-python3}" -m unittest discover -s tests/tooling -v

"${RULES_MSBUILD_PYTHON:-python3}" -m unittest discover -s tests/artifact_tools -v
"${RULES_MSBUILD_PYTHON:-python3}" -m unittest discover -s tests/project_sync -v
