# Persistent native action-cache service

On macOS ARM64, the action-cache service runs the pinned bazel-remote 2.6.2
binary directly. Install it from an already downloaded binary:

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

Use the endpoint directly with Bazel (replace the target with your project):

```sh
bash scripts/bazel.sh build //path/to:target \
  --remote_cache=http://127.0.0.1:9090 --remote_upload_local_results=true
```

For a consumer that may read but must not publish local results, set
`--remote_upload_local_results=false`. Cache entries are ordinary Bazel actions;
graph actions can also use the project-cache transport below.

The listener is loopback-only. A second worker can use SSH authentication and
forwarding without exposing an unauthenticated cache port to the network:

```sh
ssh -N -L 19090:127.0.0.1:9090 cache-host
```

On that worker, set `--remote_cache=http://127.0.0.1:19090`. Replace
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
only service HTTP listener is `127.0.0.1:9090`.
This validates restart persistence; an actual logout/reboot and independent-worker
network acceptance have not been performed.

## Project snapshots

Bazel's action cache and the MSBuild plugin use separate keys on the same HTTP
AC/CAS service. Set the endpoint in the graph action environment:

```sh
bazel build //:graph --strategy=MSBuildGraph=worker --worker_sandboxing \
  --action_env=RULES_MSBUILD_PROJECT_CACHE_URL=http://cache:9090
```

Workers forward the `RULES_MSBUILD_PROJECT_CACHE_` environment. If authentication
is needed, supply `RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN` through the environment;
do not put credentials in BUILD files or commit logs. The runner removes transport
credentials before MSBuild evaluation. Missing blobs become misses and repair;
corruption fails explicitly. Downloads are digest-checked and atomic. Bounded
parallel transfers retry transient failures three times. Observed conflicts fail,
but the HTTP backend does not provide atomic compare-and-swap for concurrent
unobserved divergent writers. See [runtime fault/recovery controls](runtime-qualification.md).
