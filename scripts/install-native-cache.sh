#!/usr/bin/env bash
# Install the pinned native cache as a per-user macOS launch agent.
set -euo pipefail
[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || { echo 'Requires macOS ARM64' >&2; exit 1; }
[[ $# -ge 1 && $# -le 2 ]] || { echo "Usage: $0 /absolute/bazel-remote [service-directory]" >&2; exit 1; }
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
binary="$1"
service_root="${2:-$HOME/Library/Application Support/rules-msbuild-cache}"
[[ "$binary" == /* && "$service_root" == /* ]] || { echo 'Absolute paths required' >&2; exit 1; }
pin="$(/usr/bin/plutil -extract sha256 raw -o - "$repo_root/tests/remote_workers/bazel-remote.json")"
actual="$(/usr/bin/shasum -a 256 "$binary" | cut -d ' ' -f 1)"
[[ "$actual" == "$pin" ]] || { echo 'Cache binary does not match repository pin' >&2; exit 1; }
label=dev.rules-msbuild.action-cache
agent="$HOME/Library/LaunchAgents/$label.plist"
[[ ! -e "$agent" ]] || { echo "Service already installed: $agent" >&2; exit 1; }
if /usr/sbin/lsof -nP -iTCP:9090 -sTCP:LISTEN >/dev/null 2>&1; then
    echo 'Port 9090 is already in use; refusing to install' >&2; exit 1
fi
umask 077
mkdir -p "$service_root/bin" "$service_root/data" "$HOME/Library/LaunchAgents"
cp "$binary" "$service_root/bin/bazel-remote"
chmod 700 "$service_root/bin/bazel-remote"
/usr/bin/plutil -create xml1 "$agent"
/usr/bin/plutil -insert Label -string "$label" "$agent"
/usr/bin/plutil -insert ProgramArguments -array "$agent"
for argument in "$service_root/bin/bazel-remote" --dir "$service_root/data" --max_size 10 --http_address 127.0.0.1:9090 --grpc_address none --profile_address none --enable_endpoint_metrics --access_log_level none; do
    /usr/bin/plutil -insert ProgramArguments -string "$argument" -append "$agent"
done
/usr/bin/plutil -insert RunAtLoad -bool true "$agent"
/usr/bin/plutil -insert KeepAlive -bool true "$agent"
/usr/bin/plutil -insert ThrottleInterval -integer 10 "$agent"
/usr/bin/plutil -insert StandardOutPath -string "$service_root/server.log" "$agent"
/usr/bin/plutil -insert StandardErrorPath -string "$service_root/server.log" "$agent"
/usr/bin/plutil -lint "$agent"
/bin/launchctl bootstrap "gui/$(id -u)" "$agent"
for attempt in {1..30}; do
    if /usr/bin/curl --silent --fail --max-time 1 http://127.0.0.1:9090/status; then
        printf '\nNative cache installed: %s\n' "$agent"
        exit 0
    fi
    sleep 1
done
echo "Cache did not become ready; inspect $service_root/server.log" >&2
exit 1
