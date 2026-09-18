#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
case "$(uname -s):$(uname -m)" in
    Linux:x86_64|Linux:aarch64|Linux:arm64) ;;
    *) echo 'The bootstrap supports Linux x86-64 and ARM64 only.' >&2; exit 1 ;;
esac
for prerequisite in curl tar sha256sum; do
    command -v "$prerequisite" >/dev/null || { echo "Missing prerequisite: $prerequisite" >&2; exit 1; }
done
source scripts/toolchain-pins.sh
mkdir -p .cache/downloads .tools/bin
install_tool() {
    local name="$1" version="$2" url="$3" hash="$4" executable="$5"
    local archive="$REPO_ROOT/.cache/downloads/$hash" stamp="$REPO_ROOT/.tools/$name.sha256"
    if [[ -x "$executable" && -f "$stamp" && "$(cat "$stamp")" == "$hash" ]]; then
        printf '%s %s: already installed\n' "$name" "$version"
        return
    fi
    if [[ ! -f "$archive" ]]; then
        curl --fail --location --silent --show-error --retry 3 --connect-timeout 20 --max-time 300 "$url" --output "$archive.partial"
        mv "$archive.partial" "$archive"
    fi
    if ! printf '%s  %s\n' "$hash" "$archive" | sha256sum --check --status; then
        rm -f "$archive"
        echo "Checksum mismatch for $name; removed download." >&2
        exit 1
    fi
    if [[ "$name" == dotnet ]]; then
        local temporary
        temporary="$(mktemp -d "$REPO_ROOT/.tools/dotnet.XXXXXX")"
        tar --no-same-owner -xzf "$archive" -C "$temporary"
        rm -rf "$REPO_ROOT/.tools/dotnet"
        mv "$temporary" "$REPO_ROOT/.tools/dotnet"
    else
        cp "$archive" "$executable"
        chmod 755 "$executable"
    fi
    printf '%s\n' "$hash" > "$stamp"
}
install_tool dotnet "$dotnet_version" "$dotnet_url" "$dotnet_sha256" "$REPO_ROOT/.tools/dotnet/dotnet"
install_tool bazel "$bazel_version" "$bazel_url" "$bazel_sha256" "$REPO_ROOT/.tools/bin/bazel"
bash scripts/tooling.sh setup-starlark
bash scripts/check.sh "$@"
