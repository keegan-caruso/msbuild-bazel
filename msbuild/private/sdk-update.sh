#!/usr/bin/env bash
set -euo pipefail
sdk_name=@@SDK_NAME@@
updater_bazel=${RULES_MSBUILD_BAZEL:-bazel}
sync_target=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bazel|--sync)
            [[ $# -ge 2 && -n "$2" ]] || { echo "Missing value for $1" >&2; exit 2; }
            if [[ "$1" == --bazel ]]; then updater_bazel=$2; else sync_target=$2; fi
            shift 2 ;;
        *) echo 'Usage: bazel run @SDK//:update -- [--bazel /path/to/bazel] [--sync //:sync]' >&2; exit 2 ;;
    esac
done
cd "${BUILD_WORKSPACE_DIRECTORY:?Run this target with bazel run}"
# A new token reevaluates the extension even for consecutive updates. Bazel owns
# the lockfile write; SDK archive facts and unrelated policy selections survive.
"$updater_bazel" mod deps --lockfile_mode=update \
    --repo_env="RULES_MSBUILD_SDK_UPDATE=$sdk_name:$(date +%s):$$"
# Record the ordinary environment so strict builds need no refresh token.
env -u RULES_MSBUILD_SDK_UPDATE "$updater_bazel" mod deps --lockfile_mode=update \
    --repo_env=RULES_MSBUILD_SDK_UPDATE
if [[ -n "$sync_target" ]]; then
    "$updater_bazel" run "$sync_target" --lockfile_mode=update
else
    echo "Updated SDK policy for $sdk_name. Run project sync, then review the lockfile and generated graph."
fi
