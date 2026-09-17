# Isolated-consumer HTTP cache comparison

This experiment compares two existing scheduling boundaries before committing to a
persistent-worker design:

1. Bazel owns each project compilation and the final runtime action. The probe
   enables HTTP remote caching in generated rule copies only; compiler actions
   remain native sandboxed, network-blocked and remote-execution-disabled.
2. One ordinary MSBuild graph build uses the native project cache, extended with an
   HTTP project index and content-addressed bundle transport. This path is outside
   Bazel and has no filesystem sandbox. It is not an integrated worker or remote
   execution implementation.

A separate ten-project whole-graph Bazel probe tests the outer-cache limitation:
unchanged graph actions recover remotely, but a new source edit invalidates the
entire action without an inner project cache.

## What is isolated

The HTTP server binds only to loopback and keeps entries in memory. Clients have
no server filesystem path. Bazel uses a fresh output base for every measured
adapter request and no disk cache; native MSBuild deletes its local project cache
and compiler outputs before every request. Native recovery uses a different
staging workspace from the seed. Bazel generates separate workspaces per request.

These are independent consumer build states on one macOS ARM64 host with the same
Nix SDK, controller and restore inputs. They are not two physical machines, a WAN,
authenticated production storage, or proof of portable keys across operating
systems. Bazel preparation reuses the existing validated controller session; its
preparation state is not a compilation cache. Native SDK identity capture is
memoized within the probe under the immutable Nix-store assumption.

## Transport

`tools/probe_http_cache.py` implements the documented HTTP GET/PUT shape for
Bazel's `/ac/<digest>` and `/cas/<digest>` endpoints in a `/bazel` namespace.
The native plugin uses a distinct `/native/index/<project-key>` mapping to a
SHA-256 ZIP-bundle digest and `/native/cas/<digest>` for the bundle. A native
index is not a Bazel ActionResult and does not seed Bazel project actions.

Uploads publish blob bytes before the project index. Project publication follows
whole-graph success, final input checks and runtime composition. Downloads verify
the CAS hash, archive member paths and sizes, bundle seals, project key and target
identity. A missing/corrupt entry triggers recompilation. Service failures open a
per-build circuit and permit a normal build without remote publication. The
experimental client rejects non-loopback endpoints; authentication, TLS, retries,
eviction, authorization and multi-host operation are future work.

The first protocol deliberately downloads each complete producer bundle at its
cache query. It does not prefetch, batch lookups, or fetch references separately.
Consequently, dependency depth can serialize network requests. This gives a
baseline against which to measure those optimizations.

## Validation and timing

The extended ten-project native probe checks relocated recovery, a root body edit,
a public API addition, missing blob, corrupt blob, archive traversal, failed-build
non-publication, changed SDK-identity salt, outage and recovery. The identity-salt
check proves partitioning; it does not execute a second SDK. Every successful build
executes the independent application oracle. Paired native/raw cold, unchanged and
body samples compare runtime DLL bytes. Bazel unchanged recovery compares DLLs
with its seed and validates remote-hit provenance from execution logs.

The HTTP server records request count, payload bytes, misses, failures and service
time. The 100-project fan runs use three alternating raw/candidate pairs for
unchanged and body edits, with a single cold sample. A second series injects 10ms
of server delay per HTTP request. This models per-request latency only: no
bandwidth cap, WAN jitter, packet loss, congestion or independent machines.

Native timing includes validation, staging, transport, compilation, runtime
composition and scratch cleanup. Bazel timing includes preparation, startup of a
fresh Bazel server/output base, HTTP transfer, sandboxing and publication. Restores,
tool bootstrap, app oracles and Bazel shutdown are outside timing. Therefore the
absolute difference between these paths cannot be attributed solely to cache
lookup or scheduler implementation. Build, preparation and transport counters are
reported separately. A retained developer Bazel server would have different costs.

## Reproduction

Inside the pinned Nix shell, use unused short output paths:

```sh
python3 -m unittest discover -s tests/native_cache -v
python3 tools/probe_native_cache.py --remote-probe --output /private/tmp/native-http-10
python3 tools/probe_bazel_remote.py --nodes 10 --repetitions 1 --output /private/tmp/bazel-http-10
python3 tools/probe_native_cache.py --remote-probe --nodes 100 --repetitions 3 --no-extended --output /private/tmp/native-http-100
python3 tools/probe_bazel_remote.py --nodes 100 --repetitions 3 --output /private/tmp/bazel-http-100
```

Both remote probes accept `--delay-ms 10`. The whole-graph probe is
`tools/probe_bazel_batch_remote.py`; pass the pinned external Nix SDK imports as
in the existing [batch reproduction](msbuild-batch-findings.md#reproduction).
Do not change controller source files during a running probe: preparation detects
those changes and refuses to reuse its session. Development smokes stopped
by this guard are not reported as passing measurements.

Bazel's documented [HTTP cache protocol](https://bazel.build/remote/caching#http-caching-protocol)
defines the action-cache and content-storage endpoints. This probe's native index
is intentionally a separate protocol. Default repository rules still disable
remote caching; no CI was dispatched and no production remote cache was contacted.

The final per-project Bazel comparison uses
`--remote_download_outputs=toplevel`: it does not force downloads of all cached
intermediate artifacts or diagnostics. Missed actions still receive their needed
dependency inputs. The initial ten-project smoke used `all`; the final comparison
supersedes those transfer counts.

A first 100-project native run recovered only 90 entries after HTTP connection
failures triggered its fallback circuit. Its expected-hit assertion failed and
that run is excluded. The final harness raises the test server's listen queue to
256 and bounds native client connections to 16. The failure reinforces that
successful output alone is insufficient evidence of cache recovery: the probe
also checks compiler counts and actual remote-download events.

Transport formats also differ: the native client ZIP-compresses a producer bundle;
this HTTP Bazel test serves ordinary CAS blobs without transport compression.
Request/byte counts describe these implementations, not a fundamental lower bound
for Bazel or a prediction for a compressed gRPC backend. Native recovery currently
fetches all producer bundles; Bazel uses top-level download policy and may avoid
some intermediate payloads.

The native implementation bounds parallel reads to 16 connections but still
publishes projects sequentially after graph success. At 100 cold misses it issues
100 index GETs and 200 sequential blob/index PUTs. With 10ms added request delay,
those PUTs alone impose roughly two seconds of extra critical-path time. Bounded
parallel publication is a concrete next optimization; downloading references
separately is more relevant when real project artifacts become large.

## Concrete portability blockers

The native experiment shares a controller/tool location across its otherwise
fresh consumer workspaces. Inspection identifies keys that still bind to that
location: the `DirectoryBuildTargetsPath` global property, the absolute plugin
path embedded in generated targets text, and environment values such as
`DOTNET_CLI_HOME`. The current key normalizer replaces the compilation workspace
root, not those independent controller paths. Moving them can cause conservative
misses even with identical source/tool bytes. This experiment therefore does not
prove reuse between independently installed controllers.

Before worker integration, move these into explicit, verified tool/location
roles and define a controlled build environment, while continuing to hash authored
source exactly. Then require a producer and consumer with different controller,
CLI-home, source and staging roots to hit the same project entries. Never obtain
portability by broadly removing paths from authored source or dropping environment
identity without constraining the executed build.

Bazel execution JSON and profiling are enabled to prove hit provenance; their
collection cost is included in the Bazel command. Raw/native MSBuild uses normal
verbosity. Parsing the retained execution JSON and checking app/DLL results occur
after the measured build interval. A subsequent performance-only run should
quantify/remove tracing overhead once this correctness boundary is stable.

## Measured results

100 projects; cold is one sample, unchanged/body are medians of three.
Both paths start without local compilation caches for every consumer request.

| Added request delay | Case | Bazel project actions | Native MSBuild project cache |
| --- | --- | ---: | ---: |
| 0ms | cold | 71.546s | 27.076s |
| 0ms | warm | 7.010s | 1.409s |
| 0ms | body | 10.080s | 1.934s |
| 10ms | cold | 74.223s | 30.526s |
| 10ms | warm | 9.566s | 1.585s |
| 10ms | body | 11.932s | 2.116s |

### Recovery traffic

| Path | Requests | Downloaded bytes |
| --- | ---: | ---: |
| bazel | 711 | 6,518,844 |
| native | 200 | 1,287,471 |

Both paths compile zero projects for unchanged recovery and one for a root body
edit. The native ten-project API edit compiles three projects, matching raw
MSBuild; the existing Bazel transitive API boundary compiles all ten (and all 100
in the scale probe). That is an implementation difference, not a necessary
property of Bazel caching. The whole-graph Bazel control recovers an unchanged
entry but recompiles all ten projects after a body edit without an inner cache.

### Decision

Remote project reuse is feasible for both scheduling boundaries. Preserve the
Bazel-owned path as the sandboxed baseline. Continue the native-cache exploration
with canonical cross-workspace/tool identities and a sandbox-aware cache broker,
then remeasure the integrated Bazel path. These timings do not yet justify
replacing the default rule path. Transfer latency tests should be expanded to
long chains and realistic bandwidth before selecting a remote deployment design.
