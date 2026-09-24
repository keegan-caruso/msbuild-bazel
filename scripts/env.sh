#!/usr/bin/env bash
# Source from repository scripts; do not depend on a previous shell's exports.
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export RULES_MSBUILD_DOTNET_ROOT="${RULES_MSBUILD_DOTNET_ROOT:-$REPO_ROOT/.tools/dotnet}"
export DOTNET_ROOT="$RULES_MSBUILD_DOTNET_ROOT"
export RULES_MSBUILD_BAZEL="${RULES_MSBUILD_BAZEL:-$REPO_ROOT/scripts/bazel-launcher.sh}"
export DOTNET_CLI_HOME="$REPO_ROOT/.cache/dotnet-home"
export DOTNET_CLI_TELEMETRY_OPTOUT=1
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
export DOTNET_NOLOGO=1
export NUGET_PACKAGES="$REPO_ROOT/.cache/nuget/packages"
export PATH="$REPO_ROOT/.tools/bin:$DOTNET_ROOT:$PATH"

# Carry the selected version into generated workspaces without a .bazelversion.
export RULES_MSBUILD_BAZELISK="${RULES_MSBUILD_BAZELISK:-$REPO_ROOT/.tools/bin/bazelisk}"
export USE_BAZEL_VERSION="${USE_BAZEL_VERSION:-${RULES_MSBUILD_BAZEL_VERSION:-$(cat "$REPO_ROOT/.bazelversion")}}"
export BAZELISK_HOME="${BAZELISK_HOME:-$REPO_ROOT/.cache/bazelisk}"
