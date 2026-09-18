# Native-cache Build/Test workflow

The .NET controller in `tools/Preparation` prepares the qualified Release/net10.0
input graph, generates `//:build` and optionally `//:test`, runs Bazel, and publishes
verified project bundles after successful input checks and tests. The measured
platform is macOS ARM64 with the pinned Nix SDK. Production commands need no Python.

## Use

Restore the selected entry normally. Packages may reside in the ordinary NuGet
global cache or in the source checkout's `.nuget/packages`. The controller copies
only the restored package closure into private build inputs and verifies it;
it does not modify the global cache. Override its location with `--nuget-packages`
or `NUGET_PACKAGES`.

Keep source, controller checkout, owned state and report output paths disjoint.
Use short paths on macOS and run inside `nix develop`. For the pinned Serilog
approval entry, save this test declaration as `/private/tmp/tests.json`:

```json
{
  "data": [
    "test/Serilog.ApprovalTests/ApiApprovalTests.cs",
    "test/Serilog.ApprovalTests/Serilog.approved.txt"
  ],
  "expectedTests": ["ApiApprovalTests.PublicApi_Should_Not_Change_Unintentionally"]
}
```

```sh
bash scripts/build.sh --bootstrap --reuse --incremental-sources \
  --workspace /private/tmp/serilog --state /private/tmp/native-state \
  --entry test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  --tests /private/tmp/tests.json --operation test --force-tests \
  --output /private/tmp/native-run1
```

Repeat without `--bootstrap` and with a new `--output`. `--bootstrap` builds the
owned action/export tools. The shell wrapper builds the controller incrementally;
for repeated calls use the selected .NET host directly:

```sh
"$RULES_MSBUILD_DOTNET_ROOT/dotnet" \
  tools/Preparation/bin/Release/net10.0/Preparation.dll workflow \
  --repository "$PWD" --workspace /private/tmp/serilog \
  --state /private/tmp/native-state \
  --entry test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj \
  --operation build --reuse --incremental-sources \
  --output /private/tmp/native-run2
```

`--operation build` selects `//:build`; `--operation test` selects `//:test` and
requires a test declaration. `--force-tests` executes VSTest even if Bazel's test
cache could satisfy the request. Tests consume verified current runtime artifacts
and declared test data; they never build or restore. Reports include timings,
compiler invocations, runtime hashes and test results. Generated files live at
`<state>/g` and persist by content.

## Local and remote reuse

`--reuse` retains a native preparation plan in owned state. Unchanged inputs skip
discovery and materialization. `--incremental-sources` permits content changes to
existing C# source-only inputs; new files, imports, package changes and other
unsupported changes require fresh discovery. The API/runtime boundary retains
zero downstream compilation for implementation-only edits while tests run the
current runtime bundle.

For remote reuse add `--remote-endpoint https://cache.example/native`. A successful
run publishes an immutable root digest as `remote.publishedSnapshot` in its report.
Select that exact digest on a fresh consumer with `--remote-snapshot <sha256>`.
Remote consumers use guarded source refresh automatically. The selected cache
endpoint and snapshot are trusted inputs; there is no mutable latest-pointer or
remote execution. HTTPS is recommended outside a local test server.

Preparation is split into source groups, metadata and per-package objects. Local
NuGet bytes reconstruct package objects only after content checks. Downloads,
ZIP members, result identities and artifacts are checked before use. Missing or
corrupt objects become cache misses. Failed compilation, failed tests, or changed
leased inputs prevent publication. Source, package, controller, policy and SDK
snapshots are checked again after consumption.

The .NET formats are `dotnet-native-workflow-v1` for owned state,
`dotnet-native-discovery-v1` for discovery proofs, and `dotnet-native-snapshot-v1`
for remote snapshots. Start with a new state directory when migrating from the
Python controller. Old Python remote snapshots miss and require fresh preparation;
they are not silently adopted. `--trust-system-nix-store` is accepted for command
compatibility but does not skip any verification in the .NET controller.

## Qualification

See [the migration record](python-removal.md#steps-3-and-4-production-workflow-and-bootstrap)
for the current .NET acceptance cases. The qualified discovery grammar, reviewed
package imports and fixed SDK inputs remain deliberately narrow. Unsupported
discovery can fall back to fresh preparation without publishing a reusable
preparation proof. Code coverage, remote execution, general NuGet support and
cross-host/platform cache reuse remain outside this qualification.

Earlier Python measurements remain in [workflow performance](native-workflow-performance.md),
[overhead optimization](native-workflow-optimization.md), and
[remote preparation](remote-preparation.md). They are historical evidence, not
measurements of this .NET controller. Python probes and reference implementations
remain available for differential tests and experiments.

## Optional Bazel installation reuse

`--bazel-install-cache /absolute/worker-cache/bazel-install` reuses the extracted
Bazel distribution under a subdirectory keyed by the exact Bazel executable's
SHA-256. Use a trusted, worker-owned tool provisioning directory, disjoint from
source, controller, SDK, state and reports. This directory contains no project
build outputs. The workflow still uses its own `state/b` output base and `state/u`
user root, so servers, analysis, action caches and repository downloads remain
isolated between fresh states. Omitting the option retains isolated extraction.
The resolved install base is recorded as `bazelInstallBase` in the report.

When manually shutting down a configured state, pass the report's same
`--install_base` startup argument along with its output base/user root; the test
harness does this automatically. Bazel manages the extracted installation's
integrity and locking. This option does not establish independent-worker cache
qualification. See [cache-hit overhead](cache-hit-overhead.md) for measurements.

## Pinned Bazel dependencies and reusable downloads

Native workspaces now stage `bazel/native.MODULE.bazel.lock`, qualified with
Bazel 8.4.2 and platforms 0.0.11. Builds use `--lockfile_mode=error`: dependency
resolution must fit this checked-in pin, and builds cannot silently refresh it.
The lockfile participates in controller/worker identity and final integrity checks.

`--bazel-repository-cache /absolute/worker-cache/bazel-repositories` shares Bazel's
content-addressed repository downloads independently of build state. Use a
worker-owned directory disjoint from source, controller, SDK, state, reports and
the optional installation cache. Bazel verifies requested object checksums. A
fresh worker can populate an empty download cache online; later consumers reuse
it without retaining project outputs, servers, analysis or action-cache state.

After provisioning, `--bazel-disable-repository-downloads` passes Bazel's
`--repository_disable_download`: missing repository-rule archives cause failure. Registry-file cache misses can
still fetch from the registry in Bazel 8.4.2, so this is not an offline-network
guarantee. It does not block NuGet restore, native artifact CAS access or other
tool networking. Use an external egress policy when network isolation is required. NuGet continues to use its
normal global package cache.

The generated lockfile's registry hashes are maintained with the pinned Bazel
and native MODULE definition. To update, deliberately regenerate a scratch
native workspace lock with that Bazel's `--lockfile_mode=update`, review the
registry/version changes, update the checked-in template and repeat dependency
cache controls and Build/Test acceptance. Do not switch production to update mode
to hide an incompatible pin. See [repository-cache results](bazel-repository-cache.md).

## Bazel remote action cache

For the qualified independent-worker slice, add:

```sh
--independent-workers --bazel-remote-cache http://127.0.0.1:9090
```

This enables **read-only** whole-action reuse, separately from `--remote-endpoint`
(the existing preparation/project snapshot store). Trusted producers additionally
pass `--bazel-remote-upload`. The two protocols can use the same bazel-remote
server; no remote executor is configured. HTTP/HTTPS endpoints are supported;
embedded credentials, queries, fragments and gRPC are rejected in this slice.
Authentication headers/credential-helper integration are not implemented yet.
Use an accessible private endpoint for now. The hosting container is independent
of the build worker and does not require .NET.

The controller binds action reuse to the existing compatible-worker identity and
requires qualified discovery. It preserves sandbox execution on misses, full
output downloads, Bazel download-digest verification and final live-input checks.
Bazel's uploads go to a private per-invocation loopback gate and are staged on
disk. Only after build/test success, lease validation and bundle validation does
the gate publish CAS objects and then action results. Failed runs discard their
staging. Publication failure is reported in `actionCachePublicationError`; a
locally validated build remains successful. Staging is bounded to 256 MiB per
object and 2 GiB cumulatively per invocation, with bounded HTTP requests.

`report.json` includes `remoteBuildHits`, executed `buildActions`, `compiles` and
`actionCache` lookup/hit keys, staged/published object counts and transfer bytes.
Cached diagnostic files describe the producer; executed-work counters come from
the current Bazel execution log. `--force-tests` continues to force actual tests.

Project seeds remain declared action inputs. A seed-free producer and a fully
seeded consumer therefore have different action keys. One seeded invocation
primes that variant, after which fresh consumers with the same seed set can hit
it. Different source/toolchain/seed inputs still miss and use the existing native
per-project cache. This is not a seed-independent cache-key optimization.
See the [qualification protocol](remote-action-cache-protocol.md) and the
[measured findings](remote-action-cache.md).
