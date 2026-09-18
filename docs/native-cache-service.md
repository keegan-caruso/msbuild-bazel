# Persistent native action-cache service

The macOS ARM64 service uses the repository-pinned bazel-remote 2.6.2 binary.
No container is required. Install using an already downloaded binary:

```sh
bash scripts/install-native-cache.sh /absolute/path/bazel-remote
```

The installer verifies its SHA-256, copies it out of temporary storage, and installs
`~/Library/LaunchAgents/dev.rules-msbuild.action-cache.plist`. It refuses to replace
an existing agent or occupy a used port. The optional second argument selects an
absolute service directory; the default is
`~/Library/Application Support/rules-msbuild-cache`.

The user launch agent starts at login and restarts after process exits. It is not
a system boot daemon and cannot serve while the Mac is asleep. Data persists under
`data/`, with a 10 GiB LRU cache limit. Service logs are in `server.log`; request
access logging and profiling are disabled. HTTP endpoint metrics remain enabled.

Use these workflow options:

```sh
--independent-workers --bazel-remote-cache http://127.0.0.1:9090 \
--remote-endpoint http://127.0.0.1:9090/native
```

Add `--bazel-remote-upload` for an accepted producer, and the explicit
`--remote-snapshot` digest for preparation/project seed recovery.

The listener is loopback-only. A second worker can use SSH authentication and
forwarding without exposing an unauthenticated cache port to the network:

```sh
ssh -N -L 19090:127.0.0.1:9090 cache-host
```

On that worker, use `http://127.0.0.1:19090` and its `/native` endpoint. Replace
`cache-host` with the actual reachable SSH host. This tunnel is a deployment
option, not evidence that a second worker has been tested.

## Operations

```sh
curl --fail http://127.0.0.1:9090/status
launchctl print gui/$(id -u)/dev.rules-msbuild.action-cache
launchctl kickstart -k gui/$(id -u)/dev.rules-msbuild.action-cache
```

To stop and prevent future login startup, boot out the service, then remove its
plist. Keep the data directory if cached content should survive reinstall:

```sh
launchctl bootout gui/$(id -u)/dev.rules-msbuild.action-cache
rm "$HOME/Library/LaunchAgents/dev.rules-msbuild.action-cache.plist"
```

## Local acceptance, 2026-09-18

Installed on the development Mac. The pinned service reported version v2.6.2,
source commit `3cb3084b57542c260860a484afcfe69557f6b27c`, and a 10 GiB limit.
A SHA-256-addressed CAS object was uploaded, the launch agent forcibly restarted,
and the recovered bytes compared exactly with the original. `lsof` confirmed the
only service HTTP listener is `127.0.0.1:9090`. The service remains running.
This validates restart persistence; an actual logout/reboot and independent-worker
network acceptance have not been performed.
