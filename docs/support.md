# Support and limits

The graph workflow with the MSBuild project-cache plugin is the sole backend.
Current baseline: SDK **11.0.100**, Bazel **9.3.2** only. Bazel 8.x is no longer supported.

Adapter compilation requires MSBuild 18 or newer and its stable
`Microsoft.Build.ProjectCache` API, as shipped in SDK 10 and newer. SDK 8/9
engines are unsupported. Repository resolution controls may still use synthetic
older version names without compiling adapters.

`USE_BAZEL_VERSION` overrides the repository `.bazelversion`; source-runtime setup
records that selection and rejects resume with a different version. Historical
qualification and timing pins below describe their original runs, not 9.3.2
qualification. The release gates in [the work queue](../WORK_QUEUE.md) track current
remaining SDK and platform requalification; each result below retains its recorded scope.

The current distribution is a reviewed Git commit selected with `git_override`;
there is no BCR release or cross-revision API/cache compatibility guarantee. See
[pinning and rollback](api.md#pin-update-and-roll-back-the-rules).

Inputs, packages, tool layouts, generated files and output ownership must be explicit. Sync does not trace arbitrary task reads or acquire
missing packages.

Native macOS ARM64 baseline checks passed `scripts/check.sh`, analysis and
execution-requirements controls on 9.3.2. Portable version controls cover generated
workspaces, explicit override precedence, repository-pin fallback, empty/legacy
overrides and source-runtime resume mismatch rejection.

With SDK **11.0.100** and Bazel **9.3.2**, full `scripts/check-dotnet.sh` passes:
all four owned projects compile and format cleanly, and the style, tooling,
artifact and ProjectSync controls pass with platform-specific skips. The 63
ProjectSync tests include seven Linux-only skips.

Graph evaluation and Restore bind the selected SDK's
`Microsoft.NETCoreSdk.BundledVersions.props` explicitly, allowing the SDK to
initialize `NetCoreSdkRoot` itself. This also supports the earlier SDK-version
imports in SDK 11.0.100. Authored properties cannot override either input.
Native macOS ProjectSync controls pass with SDK 10.0.400 and 11.0.100
(61 tests each, seven Linux-only skips) in the SDK-selection compatibility check;
the current qualification below includes the additional server-isolation controls.

Owned SDK bootstrap and Restore processes explicitly disable the CLI MSBuild
server, which is [enabled by default in SDK 11](https://github.com/dotnet/docs/blob/main/docs/core/whats-new/dotnet-11/sdk.md#msbuild-server-enabled-by-default).
This preserves their isolated process lifetimes; disabling Roslyn shared compilation
alone does not disable the MSBuild server. Restore controls verify that an ambient
server opt-in cannot override this policy. This compatibility policy does not change
the selected SDK or upstream product version.

Full native graph acceptance passes all **17 slices** and the Bazel quickstart,
including offline supported package SDKs, signed archive identities, MTP/VSTest
protocols, tool replay and independent payload publication. Replay fixtures make
their copied roots writable so Restore can create its temporary `NuGet.Config`;
the default HTTP-cache fixture isolates macOS LocalApplicationData in its native
home location. Production cache and output-permission policies are unchanged.
Linux execution and source-runtime production have the separately scoped evidence below.

The historical 9.3.0 upgrade passed 29 analysis/integration checks on Linux ARM64, including
8.8 compatibility, SDK facts, cached/uncached workers, compiler selections and
recursive-source HTTP Restore/project recovery. Cached HTTPS SDK acquisition also
passed with all downloader URLs blocked and metadata removed. Run the corresponding
current-baseline gate with:

```sh
SDK_VERSION_CACHE_URL=http://cache:8080 DYNAMIC_SOURCE_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{sdk_versions,quickstart,sdk_locks,workers,recursive_sources,resolved_inputs} \
  --test_output=errors
```

The earlier 481-compilation runtime baseline and historical source-SDK component
consumers retain their recorded 9.2 qualification. The downloaded-SDK runtime
slice and current source-SDK producer have separate 9.3 results.

## Cache and worker diagnosis

Start with the exact rules commit, SDK version, Bazel version, execution platform
and command. Keep the first failing run before retrying; a successful retry does
not explain it. Use a fresh disposable output base when checking independent
recovery. Separate SDK acquisition, whole-action hits and project snapshot hits.

| Symptom | Evidence to inspect | Next check |
| --- | --- | --- |
| Unchanged Bazel action runs again | Execution log `mnemonic`, `runner` and `cacheHit`; changed command/action environment | Compare declared inputs, flags and SDK/rules pins. A cache endpoint flag change can change the experiment. |
| Graph runs with zero project hits | Graph `report.json` hits/misses, prepared Restore and worker fields | Confirm actual worker selection or project endpoint, then compare input bytes, Unix modes, membership, global properties and SDK inventory. Cache misses alone do not prove a platform is unsupported. |
| Sync or Restore repeats compilation | `PROJECT_SYNC_CACHE` and `PROJECT_SYNC_RESTORE_CACHE` diagnostics | Confirm qualified execution and explicit sources; compare both pre/post-build observations. Restore a file's original mode when testing rollback, rather than assuming `0644`. |
| TLS handshake/body timeout | First client error and cache/relay connection counts | Confirm guest TLS trust and endpoint reachability, then bound concurrent connections. Preserve corruption/authentication failures; do not disable verification to make a retry pass. |
| Worker hangs, exits or truncates output | Bazel worker log, process exit/signal, bounded diagnostic tail and graph report | Distinguish request deadline, child termination and retained-engine failure. Preserve the first error and retry with a fresh worker to test recovery. |

For a short graph diagnostic, set `profile_build = True` on the authored graph
wrapper, then retain its `bazel-bin/NAME.graph/report.json`, sibling binary log and
Bazel `--execution_log_json_file=PATH` output. Profiling adds work; its overlapping
phase times are not an unprofiled performance comparison. Remote counters count
successful logical payloads, excluding retry traffic and HTTP framing; unchanged
cache size or a read-only setting alone is not a measurement of network PUTs.
In the consumer workspace, set the sync launcher and prepared-action environments
together:

```sh
RULES_MSBUILD_SYNC_PROFILE=1 bazel run //:sync \
  --action_env=RULES_MSBUILD_SYNC_PROFILE=1
```

Retain the `PROJECT_SYNC_PROFILE` phase records from the command log. The
launcher inherits its process environment; cached preparation uses `--action_env`.

The worker keeps a diagnostic tail of at most **1,048,576 characters** while
continuing to drain output. Its request deadline is one hour; termination waits
up to five seconds. Project-cache HTTP operations have a two-minute deadline,
including streamed body reads. These are failure bounds, not suggested workload
budgets. Use a shorter external qualification deadline with owned-process cleanup
for small experiments; do not change production bounds merely to hide a failure.

Keep a bounded evidence bundle: a short reproduction/limits file, exact pins and
command, first failure plus one controlled retry, graph/sync summaries and only
the execution/binary logs needed to explain the issue. Record wall time, exit code,
peak memory method and disk growth separately. Logs can contain source paths,
properties, task output or credentials; inspect them before sharing and never
include bearer tokens, private cache configuration or entire workspaces by default.
Preserve reports outside Git, remove only owned disposable worktrees/processes,
and close their sessions after cleanup. Independently managed services and caches
remain intact.

## Dependency updates and security triage

Repository maintainers own bootstrap pins, declared package catalogs and optional
benchmark dependencies. Before changing a pin, check its upstream advisory and
fixed version, identify the repository call sites, and validate the affected
workflow in a fresh tool environment. Keep source-product and bootstrap versions
separate; updating one does not qualify the other. Preserve the old pins and
qualification revision for reproducing historical measurements.

The optional benchmark environment pins GitPython **3.2.1** and its dependencies.
This replaces 3.1.62, which had seven open GitHub dependency alerts at review
(five high and two moderate). The pinned upstream bazel-bench invokes GitPython
for repository clone, fetch and checkout, so this dependency participates in the
benchmark workflow even though normal builds do not install it. A fresh
`scripts/setup-bench.sh` environment passed dependency consistency checks and
real clone/fetch/checkout controls against the pinned bazel-bench implementation;
the four owned measurement tests also passed. This does not audit arbitrary
benchmark repositories or establish that future dependency alerts are absent.

For a release candidate, review current dependency alerts and supported platform
qualification in [the work queue](../WORK_QUEUE.md), run the affected behavioral
checks and scaffold/style gates, and preserve the exact pins, report and remaining
limits. Publish through a reviewed change; do not describe an unrun platform or a
warm local cache as a qualified release.

## Shared cache on two Macs

The general Apple Container wrapper defaults to pinned Ubuntu 26.04 ARM64.
Set `RULES_MSBUILD_CONTAINER_ARCH=amd64` for explicit Rosetta execution on Apple
silicon. The image installs the Ubuntu 26.04 .NET prerequisites; SDK 11.0.100
and Bazel 9.3.2 remain independently pinned.

Container payload, workspace and SDK bootstrap extraction use Ubuntu's pinned
`libarchive-tools` 3.8.5-1ubuntu2.3. GNU tar in this Ubuntu release fails nested
extraction under Rosetta when `openat2` returns `ENOSYS`
([Ubuntu report](https://bugs.launchpad.net/ubuntu/+source/tar/+bug/2166326)).
Source archive creation retains GNU tar. Outside the container, bootstrap uses
`tar` by default; `RULES_MSBUILD_TAR` explicitly selects another executable.
SDK archives are hash-verified before that executable is called.

Fresh Ubuntu 26.04 ARM64 and AMD64 Rosetta containers passed the public
downloaded-SDK quickstart: sandboxed graph Build, executable test, greeting with
explicit `RuntimeInformation.ProcessArchitecture` assertions (`Arm64` / `X64`),
and sync `--check`.
This validates the general SDK/Bazel path; it does not qualify a source-built
x64 runtime producer or Linux worker/recovery behavior.

Use the same reachable HTTP(S) endpoint for both hosts; keep its address in the
host environment, outside Git. Each host runs an independent consumer:

```sh
# Export a reachable endpoint as RULES_MSBUILD_SHARED_CACHE_URL first.
bash scripts/run-apple-container.sh bash scripts/bazel.sh test \
  //tests/integration:quickstart --test_output=errors
```

With `RULES_MSBUILD_SHARED_CACHE_URL` set, the wrapper forwards it into the guest
and writes guest-only Bazel defaults: the same URL for the action cache and
`RULES_MSBUILD_PROJECT_CACHE_URL` (including action environment), no disk action
cache, synchronous uploads and complete output downloads. It bounds Bazel to two
jobs, one local test and one MSBuild graph worker instance. This does not enable
worker execution or change sandboxing. Command-line flags, including fixture
recovery controls, can override these defaults; consumers that ignore Bazel rc
files must pass the cache flags explicitly. An absent URL leaves cache and job
configuration unchanged. `RULES_MSBUILD_CONTAINER_PREBUILT=1` is forwarded too;
use it only with a prepared image matching repository pins.

If the Linux guest cannot route to the HTTPS endpoint, optionally set
`RULES_MSBUILD_SHARED_CACHE_SOCKET` to an existing host UNIX socket whose service
forwards raw bytes to that endpoint. The wrapper mounts the socket and starts a
guest TCP relay, deriving its loopback port and `/etc/hosts` mapping from the
shared HTTPS URL. TLS still verifies the original server hostname; the relay does
not terminate TLS or change either cache URL. Use a DNS hostname without URL
credentials. The host must provision and keep that socket service running; the
wrapper does not install it. This transport is opt-in and requires Python 3 in
prebuilt images. Relay process lifetime follows the disposable container.

Run one heavy container per host, with the wrapper's four CPU / 6 GiB defaults.
Split independent suites or producer/consumer runs between the Macs; a shared
cache reuses results, it does not distribute compilation. Check `df -h` before
large source builds and leave room for the complete active output tree and image.
The remote cache avoids retaining duplicate persistent action caches; active
outputs, expanded SDKs/packages and repository downloads still need local space.
Repository acquisition is separate from action/project reuse: this setting does
not configure an HTTP repository-contents cache or eliminate SDK downloads.

Containers use `--rm` and keep only explicitly written `/evidence` files and the
run log in `artifacts/apple-container/run.*`. Put reports in `/evidence`, rather
than copying the workspace or output base back to the host. Review and prune old
evidence when it is no longer needed. Producer/consumer recovery evidence still
requires fresh workspaces/output bases and a stopped producer; warm local reuse
alone does not qualify cross-host recovery.

The wrapper forwarding/default controls pass with
`python3 -m unittest discover -s tests/tooling -p test_apple_container.py -v`.
The separate `test_shared_cache_guest_relay.py` controls exercise bidirectional
TCP/UNIX bytes and half-close behavior, including delayed and sustained reverse
responses and a nonclosing peer. After either side reaches EOF, the relay bounds
idle reverse draining to 30 seconds and resets that deadline on progress;
portable controls also cover a blocked reverse write. These mock the host launcher
and execute guest configuration. A fresh Ubuntu ARM64 guest on Bazel **9.3.2** also passed
public quickstart Build/test/run with the generic relay and shared action/project
cache URLs: the sandboxed graph action actually executed, loaded `GraphCache`,
and the app printed its expected greeting. The command used
`--remote_accept_cached=false` for the test build and retained an execution log;
HTTPS cache status also succeeded. This qualifies Linux Bazel/MSBuild access,
not stopped-producer cross-host Linux recovery, worker reliability or resource
sufficiency. Keep the consumer and rules checkout outside `/tmp`, or under one
common scratch parent: Bazel's hermetic `/tmp` can hide a sibling local override.

## Native Linux x64 controls

On native Ubuntu 26.04 x64 with SDK **11.0.100** and Bazel **9.3.2**, the
four-CPU / 6 GiB qualification passed all four owned builds and format checks,
plus 5 style, 81 tooling, 19 artifact and 63 ProjectSync tests without skips. Nine
standalone worker-broker, publication, transfer, input-integrity and output-ownership
controls also passed. Worker preparation additionally passed with a zero cache budget.

A separate public quickstart seed populated a bounded local HTTP action cache and
stopped its Bazel server. A fresh output-base consumer recovered the graph action,
executed its test with test-result caching disabled, and matched all 112 output
tree entries, including bytes and modes. The server counted 498 successful consumer
GETs and zero consumer PUTs; seed and consumer kept the same project-cache read-only
setting. This qualifies same-host whole-action recovery, not cross-host recovery,
Bazel's x64 worker strategy or native x64 source production.

Reproduce with the [manual recovery driver](../tests/graph_build/linux_action_recovery.py)
on native Linux x64, using a clean checkout and a fresh output directory:

```sh
python3 tests/graph_build/linux_action_recovery.py /tmp/action-recovery \
  --rules "$PWD" --bazel "$PWD/.tools/bin/bazelisk" \
  --expected-revision "$(git rev-parse HEAD)"
```

The original cache-reuse fixtures assumed files started at mode 0644. Controlled
retries reproduced both failures under umask 002 but passed under 022; after
restoring each file's actual starting mode, both tests passed under 022, 002 and
077. The SDK file-content and mode inventory was unchanged. The original run did
not record its umask, so its exact inherited mode is not established.

With `RULES_MSBUILD_DOTNET_ROOT` set to the pinned SDK, build `GraphBuild` and
`ProjectSync` in Release, then run:

```sh
for test in worker_supervision worker_preparation publication_queue worker_lifecycle \
  remote_streaming remote_publication remote input_integrity output_ownership; do
  python3 "tests/graph_build/$test.py"
done
python3 tests/graph_build/worker_preparation.py --cache-mb=0
python3 -m unittest discover -s tests/project_sync -p test_sync.py -v
```

## SDK 11 platform qualification

SDK **11.0.100** / runtime **11.0.0** and Bazel **9.3.2** pass these checks:

| Environment | Observed scope |
| --- | --- |
| Native macOS ARM64 | Owned build/format and tests, all 17 graph acceptance slices, actual Bazel quickstart test. |
| Ubuntu 26.04 ARM64, four CPUs / 6 GiB | Owned checks including all 61 ProjectSync controls available at that revision, real broker lifetime/preparation, cached and uncached workers, evaluation worker, quickstart and automatic worker defaults. The default-worker body edit reuses two projects and compiles one. |
| Ubuntu 26.04 AMD64 under Rosetta, four CPUs / 6 GiB | Fresh prebuilt toolchain image, public quickstart sync/check, app greeting and forced executable test. |
| Native Ubuntu 26.04 x64, four CPUs / 6 GiB | Full owned gate without skips, nine broker/transfer/input controls, and stopped-seed fresh-output HTTP graph recovery with forced test execution and zero consumer PUTs. |
| Ubuntu 26.04 ARM64 source producer, four CPUs / 12 GiB | Official source-to-app setup, managed compilation, runtime packaging, two forced tests and retained host launcher. The upstream product remains .NET 10; see [product qualification](#complete-source-runtime-product). |

The Rosetta integration-test archive helper fails in GNU tar while following Bazel
input symlinks (`Function not implemented`); it does not reach the test. The direct
public quickstart above passes without that helper. This limitation is separate
from SDK/archive extraction, which uses the pinned libarchive tool.

Source-runtime bootstrap uses SDK 11 while its pinned upstream product remains
runtime 10.0.0. The retained source-built SDK 10.0.100 and NativeAOT compiler retain
their own recorded pins; they are not SDK 11 products.

## Downloaded SDK platforms

Downloaded-SDK controls passed on native Linux ARM64 and Linux x64 **under
Apple Rosetta**: 29 analysis/integration checks across the recorded 8.8.0 / 9.3.0 pins,
plus 21 SDK/runtime repository controls. Scope: SDK selection/locks, quickstart,
SDK-only Web/Razor Build/test/Publish and HTTP recovery, cached/uncached sandboxed
workers, body/API edits and raw MSBuild output parity. The Web fixture checks the
actual process architecture; fixture declarations select the host SDK RID.

```sh
SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{quickstart,sdk_locks,sdk_policies,sdk_web,workers} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

The x64 controls used amd64 SDK/Bazel binaries in Ubuntu containers on an ARM64
Mac. This establishes emulated x64 behavior, not native x64 performance or
source-built SDK/runtime qualification. Current native x64 owned checks,
quickstart and HTTP recovery are recorded in the [SDK 11 matrix](#sdk-11-platform-qualification);
Native x64 source-runtime production is covered [separately](#complete-source-runtime-product);
Native x64 source-SDK production and local consumers are covered
[separately](#native-ubuntu-2604-x64-sdk); automatic workers and whole upstream
graphs remain unqualified.

Native macOS ARM64 passed `//tests/integration:{quickstart,native_sdk}` on
the recorded 8.8.0 / 9.3.0 pins with SDK **10.0.400**: the public catalog's packages,
Razor/Publish, app/tests, body/API reference checks, sync/check and an independent
strict-lock source/output-base consumer. These four controls also passed on
native Linux ARM64. All 24 SDK/runtime repository controls
also passed on macOS / 9.3. The portable `native_sdk` suite is ready for native
Linux x64, but that specific suite was not run in the native SDK 11 matrix. These
macOS controls use ordinary sandboxed actions, with remote actions disabled;
Linux workers, published-byte parity and HTTP recovery retain their separate
qualification above.

`//tests/integration:visual_basic` passed on Linux ARM64 with SDK **10.0.400**
and the recorded 8.8.0 / 9.3.0 pins: explicit `.vbproj` roots/mappings, a C# consumer,
body edits, execution and independent disk-cache recovery. VB inputs remain
explicit; automatic compiler-input qualification and Compile globs are C# only.

## Qualified SDKs

The SDK suites below were qualified on Linux ARM64 with Bazel 8.8.0 / 9.2.0:
public sync, raw MSBuild parity, edits, failures and cached/uncached workers.

| SDK / project | Qualified behavior | Native suite (`//tests/integration:`) |
| --- | --- | --- |
| .NET | Managed graphs, Build/Publish, app/test layouts | `quickstart`, `workers` |
| Traversal 4.1.82 | Nested coordinators, conditional/wildcard references, multi-target children, Pack/Publish | `traversal` |
| NoTargets 3.7.0 | `.proj`/`.csproj` file producers, nested Traversal, explicit products and downstream invalidation | `notargets` |
| Worker + Hosting 10.0.11 | Worker template, Build/Publish and bounded execution | `worker_sdk` |
| IL 10.0.0-rtm.25509.106 | `.ilproj`, managed consumers, deterministic DLL/PDB, Build/Publish | `il_sdk` |
| Arcade 10.0.0-beta.25509.106 | SDK composition, versioning, Build/Pack/Publish and generated packages | `arcade_sdk` |

Web/Razor [graph controls](../tests/graph_build/web.py) cover compile/replay, Razor
edits and assembly attributes; source-built Razor consumers are covered below.

`//tests/integration:sdk_web` passes cold on Ubuntu 26.04 ARM64 with SDK
**11.0.100** and Bazel **9.3.2**, using its bundled ASP.NET framework without
`runtime_host`. Build/test and Publish serve a compiled Razor page and published
static assets; content edits require no sync. Raw builds and fresh-source/output-base
rebuilds compare exact file inventories/hashes and all static endpoint metadata
except validated SDK `Last-Modified` timestamps. Endpoint sidecars must match their
inventory hashes. The same cold comparison passes the catalog fixture with SDK
**10.0.400**. These are bounded four-CPU/six-GiB guest controls, not general
Blazor/workload or real-project Publish qualification.

Historical SDK **10.0.400** results on the recorded 8.8.0 / 9.3.0 pins additionally
qualify HTTP action and forced project recovery: all published bytes match exactly,
the edited web app executes, and project recovery yields three hits / zero
compilations. Actual cache-hit comparisons remain byte-exact, including endpoint
timestamps; the cold-rebuild exception does not apply to either cache recovery path.

The [package-backed catalog](../examples/catalog-web/README.md) qualifies five
projects with Newtonsoft.Json / Humanizer, embedded data, Razor and static assets.
`SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test
//tests/integration:catalog_web --test_output=errors` passed both pins on native
Linux ARM64: ordinary/graph MSBuild Publish parity (same timestamp exception),
body/API edits and test invalidation. The body edit retained reference bytes with
four project hits / one compilation; the API edit yielded one hit / four
compilations. Bazel recovered both Restore and graph actions remotely; forced
HTTP project recovery (five hits / zero compilations) preserved every published byte and ran the app.
The public example uses the regular graph workflow; the fixture separately enables
Linux prepared Restore/workers. Evaluation reuse is off: Razor API changes can
trigger SDK reevaluation, which the retained-evaluation guard rejects.

`bash scripts/bazel.sh test //tests/integration:sdk_locks --test_output=errors`
passed 8.8.0 / 9.3.0 on Linux ARM64: automatic metadata resolution, native lockfile
facts, platform expansion, fresh-base recovery without metadata, extension-change
reuse, stale-pin rejection, archive hash/layout guards and private archives. Cross-version recovery
also passed after recording each Bazel version's registry entries. SDK **10.0.302**
(absent from the former catalog) passed sync/app/tests and a fresh clone in strict
lockfile mode with metadata removed; **10.0.400** retains quickstart coverage.

Historical `//tests/integration:sdk_versions` evidence passed **8.0.425**, **9.0.318** and
**11.0.100-rc.1.26425.128** on both Bazel pins: SDK-derived adapter frameworks,
sync/check, app/tests, body/API edits and fresh-base recovery without metadata.
Each SDK recovered the whole graph action through Bazel's remote cache; forced
HTTP project recovery returned three hits / zero compilations and identical outputs.
These results predate the stable-only adapter requirement. The active matrix
uses SDK 10.0.302 and 11.0.100; see [adapter requirements](api.md#sdks).

Historical `//tests/integration:sdk_policies` evidence passed both Bazel pins on Linux ARM64: patch
fallback, latest patch/feature selection, prerelease ordering/filtering, locked reuse
after metadata changes, platform expansion, old-lock migration without metadata,
strict fresh-base recovery, invalid-fact rejection and explicit refresh. A real
`9.0.300` / `latestPatch` request selected **9.0.318** and passed sync/check/app/tests.
The declared `@dotnet//:update` target passed consecutive refreshes, preservation of
unrelated pins/hashes, metadata-failure recovery, strict lock reuse and optional
sync on both Bazel pins. The combined `--nuget-update` sequence also passed both
pins with SDK 9.0.318: stale native locks failed offline, package changes resolved
before sync, and failed package resolution preserved locks and the graph.
The active real-SDK consumer now requests `10.0.300` / `latestPatch` and
expects 10.0.302; synthetic SDK 9 prerelease resolver controls remain unchanged.
All 24 SDK/runtime repository controls passed on native
macOS ARM64 / 9.3. Other roll-forward policies
remain unsupported; selection uses published releases, not installed SDKs.

`//tests/integration:source_globs` passed both pins on native macOS ARM64 and
Linux ARM64: local/external-module graph compilation, body edits, pinned membership
and rejection of undeclared cross-repository sources.

`//tests/integration:evaluation_worker` passed the recorded 8.8.0 / 9.3.0 pins on Linux ARM64:
reviewed body/API reuse, fresh build state, evaluation-input/task changes and failed-
build recovery. Retention requires explicit compiler-only input review; see
[configuration](api.md#caching-and-workers) and [runtime timings](performance.md#reviewed-evaluation-reuse).

## Project qualification cache

Closed sync automatically enables HTTP project reuse when complete `srcs`,
package/reference qualification, the declared qualified Linux execution capability
and a project HTTP endpoint are available. Explicit `qualification_cache = True`
retains the forced Linux path; `False` disables it. See [default eligibility](api.md#sync). Linux ARM64 / SDK **10.0.400** passed small controls
on both Bazel pins: normal-mode declaration parity, forced preparation with an empty
local cache, body/API invalidation, independent-branch reuse, app execution and
Newtonsoft.Json **13.0.3** package-tree materialization/recovery.
The ProjectSync controls cover props and executable-mode changes, multi-target
selection, implementation/reference DLLs, XML copies, failed builds, corrupt
artifacts/metadata, relocation, source/SDK aliases and overlapping output owners.

Environment fingerprinting reuses content digests for file links resolving to the
same target path inside the immutable SDK during one pass. Logical names, order
and modes remain keyed; later passes reread bytes. External resolved paths bypass
reuse; directory aliases and hard links may miss reuse. The SDK must remain
immutable during the pass. Production/legacy comparisons use the same assembly
bytes and pass for the actual SDKs below, empty/plain/linked fixtures, renamed paths,
mode/content changes with restored timestamps and retargeted links between passes.

Ubuntu 26.04 ARM64 warm-cache complete-environment measurements use four alternating
legacy/production pairs; these are fingerprint timings, not end-to-end sync gains:

| SDK layout | Legacy median | Production median |
| --- | ---: | ---: |
| Downloaded SDK 11.0.100 | 0.326 s | 0.253 s |
| Retained source SDK 10.0.100 (`e043c131`) | 0.704 s | 0.554 s |

After building ProjectSync, run
`python3 tests/graph_build/qualification_environment.py --full` on Linux with
`RULES_MSBUILD_DOTNET_ROOT` set and `/usr/bin/bwrap` installed. This checks the selected
real SDK and measures synthetic plain/linked layouts. Omit `--full` on macOS to
check SDK records only; complete environment hashing requires the Linux system files.

The conditional-default fixture passed on Linux ARM64 / SDK **10.0.400**, both
current Bazel pins: package-free closed sync, absent-endpoint and target-only
capability fallback, explicit disable/forced-prerequisite controls, automatic
qualification/seeding and portable consumers. The three-project Build recovered
all seeded snapshots; body/API edits retained **two / one** project hits and matched
fresh DLL/PDB bytes with the project cache disabled. Inferred Restore keys source
contents without making those contents shared Build inputs.

```sh
QUALIFICATION_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/integration:defaults --test_output=errors
```

The complete source-runtime graph also passed on 9.3: all 563 eligible projects
replayed through HTTP; Pipelines body/API edits ran 11/26 Csc tasks and retained
byte-identical declarations. With `--cache-url`, source-runtime setup also enables
reviewed Restore reuse for `PipeOptions.cs` and its reference source. Its Bazel
launcher limits remote cache connections to eight and uses a 60-second timeout.
`--bazel-cache-read-only` freezes disabled Bazel action uploads for a source-runtime
setup; `RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1` separately disables project
snapshot uploads. Portable controls verify both policies and saved wrapper identity;
portable wrapper controls check both cache-enabled and cache-free arguments. Only those
compiler-only contents are exempt; file names/modes, definitions, packages and
other contents remain keyed. Small Bazel controls on both pins verify body/API
Restore hits and props/package misses. Initial seeding still performs the SDK
Build; [timings](performance.md#source-runtime-product) separate qualification
from ordinary builds.

Verified Restore snapshots passed small controls for compiler-only edits, source
membership/modes, failed compilation, corrupt assets, authored Restore-hook inputs,
empty generated directories and synthetic package-SDK resolution after replay.
Serial/parallel multi-target qualification retains SDK selections with full-state
worker transfer; the small cache fixture reports zero worker evaluations. Root
`restoreReuseInputs` requires a separate review of compiler-only contents; arbitrary Restore task reads remain declared.
A stopped-producer, relocated-VM control recovered Restore and all four projects
through HTTP, including package-SDK resolution, with no local cache, zero
compilations, identical declarations and matching artifact digests.

Build snapshot seeding (automatic with the declared qualified execution capability,
or forced with `seed_build_cache = True`) passed a three-project chain, a five-node/two-framework
graph, a query-only coordinator, globs over unselected files and generated-file
conditions on Linux ARM64,
SDK **10.0.400**, the recorded 8.8.0 / 9.3.0 pins. First ordinary
Builds recovered all three/four project snapshots without compilation. A fresh
source/output-base consumer recovered through HTTP with Bazel action caching off;
owned outputs matched uncached Build bytes, excluding the ordinary protocol's
private `AssemblyReference.cache` omission. Body/API edits missed one/two projects;
configuration changes, failed compilation and a reviewed target mutating Restore
inputs could not reuse stale products or publish invalid declarations. Replayed
qualification snapshots also seeded complete Build snapshots. Real Traversal **4.1.82**
and NoTargets **3.7.0** controls recovered both assemblies, ran the declared file
producer and matched uncached output bytes. SDK archive copies keep data permissions
before compilation; executable-mode hashing remains enabled.

On 9.3, the complete managed runtime graph (631 configurations) recovered all 563
seeded assembly snapshots with matching keys and manifest bytes. A separate binlog
control recorded zero Csc/Vbc calls and zero build-node evaluations. This qualifies
managed Build handoff; Pack/Publish seeding and other platforms remain unqualified.

Requires the qualified Linux/bwrap environment; the Apple container must allow
user namespaces and avoid read-only `/proc` submounts, as in
`scripts/run-apple-container.sh`. This is stable-path isolation, not tracing of
arbitrary task reads. Declare custom inputs and tools. Other .NET SDK versions,
platforms and RBE remain unqualified for this option. Non-assembly projects run
normally; overlapping output owners and their consumers skip reuse. See [configuration](api.md#compiler-selections)
and [measurements](performance.md#project-qualification-reuse).

```sh
QUALIFICATION_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/integration:{qualification_cache,qualification_seed} --test_output=errors
```

The broader legacy acceptance command still rejects its unsupported `Fixture.Sdk`
synthetic on both starting and candidate runners. Its protocol slice also stops
at archive/lock content-hash mismatches before graph sync. Those fixtures do not
qualify this cache option; use the native integration command above.

## Downloaded SDK and runtime sources

The public `dotnet.sdk(version="10.0.400")` → native package update/check → offline
sync/check workflow passed on runtime v10.0.0, Linux ARM64 / Bazel 9.3.0. It retains
upstream SDK compiler behavior, including out-of-process `Runtime="NET"` tasks.

| Slice | Configurations / compilations | Archives / native locks | Compiled files matched |
| --- | ---: | ---: | ---: |
| Four managed roots | 182 / 163 | 106 / 91 | 1,447 |
| 39 roots / eight suites | 543 / 481 | 141 / 265 | 3,622 |

Both slices passed paired body/API parity, actual compiler-workset controls and
independent stopped-producer recovery: normal Restore + graph action hits, then
forced HTTP project recovery with zero compilations and identical bytes/modes.
The small slice's app verified and exercised the source-built Pipelines DLL on the
downloaded host. The large slice executed an app on its declared source-built native
runtime plus eight upstream suites. A healthy independent consumer now actually
executes all nine tests after normal Restore/graph action recovery and after forced
**481 HTTP project hits / zero compilations**. Both match **10,780 retained files**
including modes, **118,952 passed / 64 skipped** upstream cases, and loaded source-runtime
hashes. Test-result caching is disabled and the producer is stopped. See [measurements and reproduction](performance.md#large-downloaded-sdk-graph).
A [runtime CI demo](performance.md#runtime-ci-demo) separates full build recovery
from actual suite execution and includes an optional body-edit rehearsal.
Clean image/source/cache setup, interrupted resume and independent recovery after
verified producer deletion also pass on Linux ARM64; test-result caching is disabled.
Batched project layouts passed three-project baseline/body-edit byte-and-mode
parity on Bazel **8.8.0 / 9.3.0**, with one layout action and pre-build `aquery`.
Unknown configured projects and escaping destinations fail analysis.
On the large graph, one batch replaces 124 host-directory exports and matches all
490 host files/modes. A stopped-producer consumer recovered **186 build actions
and nine test results remotely**, then body/API edits each executed all nine tests
with **6 / 17** compilations and raw output/case parity. These controls use 9.3.0.
This is a bounded managed graph with declared native producers, not the entire
runtime repo, a full source-built SDK, Linux x64 or remote execution.

## NuGet inventories

`//tests/integration:solutions` passed `.sln` / `.slnx` update, strict child locks,
offline sync/test, native graph DLL parity, configuration mappings, exclusions,
solution dependencies and stale-file rejection on **8.8.0 / 9.3.0**, Linux ARM64.
`solutions_remote` fresh consumers recovered four projects with zero compilation,
identical product bytes/modes and successful execution for both formats/pins.
Single solutions without custom solution hooks are qualified; see [API](api.md#sync).

`//tests/integration:nuget_update` passed **8.8.0 / 9.3.0** on native Linux ARM64:
explicit update/check, offline native locks, app/Razor/Publish and rejection of
corrupt native hashes or malformed manifests. Failed resolution preserved locks
and contracts. The public update command also passed on macOS ARM64 / 9.3.

`//tests/integration:nuget_graph` passed both pins on Linux ARM64: central versions,
transitive Options dependencies, netstandard2.1/net10.0 with different Newtonsoft
versions, a packaged CA1822 failure control and an independent strict-lock consumer
with downloads disabled. Restore validation also skips inner-framework functions
inside false item groups, using MSBuild's native `ProjectInstance` evaluator;
incomplete Restore and missing SDKs still preserve locks/contracts. The graph action
recovered through HTTP. Root analyzer
settings are declared inputs; config-only edits enable/disable CA1822 without sync
and reject stale compilation. Automatic SDK discovery stops
at the declared workspace; nested/global configs are retained and authored outside
reads still fail validation (31 sync controls). The package-backed
catalog now uses generated inventories; its raw Publish/edit/recovery controls above
retain the same scope. Native macOS passed its app/Razor/Publish tests and checked a
9.3-generated contract unchanged with 8.8.

`//tests/integration:nuget_hierarchy` passed both pins on Linux ARM64: native
config inheritance/clears, disabled sources, nested source mappings, config-only
attestation, offline sync/test and rejection of outside configs. Traversal/NoTargets
HTTP action recovery also passed with native config discovery enabled. The hierarchy
control also passed on native macOS ARM64 / 9.3.

`//tests/integration:nuget_configured` passed both pins on Linux ARM64: shared
graph/entry properties, all-framework native locks, escaped property values,
offline sync/test and rejection of conflicting shared-project locks or reserved
Restore overrides.

`//tests/integration:nuget_shared_projects` passed both pins on Linux ARM64:
project-specific locks in shared directories, selected-SDK binding, strict dependency
drift rejection and atomic rejection of colliding lock names.

`//tests/integration:nuget_sdks` passed both pins on Linux ARM64: generated
Traversal **4.1.82** / NoTargets **3.7.0 → 3.7.56** inventories, global/inline SDK
selection, locked child dependencies and SDK-version invalidation. Incomplete
Restore and missing SDKs preserved locks/contracts. An independent consumer with
downloads disabled recovered Restore and graph actions through HTTP and preserved
all published product bytes. Unused SDK declarations require no archive.

IL and Arcade fixtures now use generated inventories. Both pins passed native
update/check, offline sync, raw Build/Publish parity, edits and failure recovery;
Arcade also passed Pack/package-consumer parity. Independent HTTP consumers
recovered two projects with zero compilation, identical bytes/modes and successful
execution. Pins: IL **10.0.0-rtm.25509.106** (including ILAsm/ILDasm), Arcade
**10.0.0-beta.25509.106**. Suites: `il_sdk`, `arcade_sdk` and their `*_remote` controls.

Reproduce with `SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test
//tests/integration:{nuget_update,nuget_graph,nuget_sdks,native_sdk,catalog_web,sdk_policies} --test_output=errors`.
Scope: SDK **10.0.400**, public NuGet.org V3 and standard project lockfiles;
[API](api.md#nuget-updates) lists update limits. No new x64 or source-built qualification.

## Downloaded runtimes

Active runtime fixtures compile net10.0 with SDK 10.0.302. Runtime lock controls
use 9.0.20 for older-major rejection, 10.0.12 for matching-major execution and
11.0.0 for default rejection / explicit `RollForward=Major` execution. ASP.NET
controls use CoreCLR/ASP.NET 10.0.12 and ASP.NET 11.0.0. These updated fixture
pins require fresh qualification; the results below retain their historical pins.

Historical SDK **9.0.318** evidence compiled a net9.0 app that ran on runtime **9.0.20**, rejected
**8.0.31 / 10.0.12** by default, and ran/tested on **10.0.12** with the app's
`RollForward=Major`. Metadata controls cover apphost exclusion, native facts,
platform expansion, metadata-free recovery, extension changes, stale pins, corrupt
hashes/archives and private layouts. Fresh-base recovery hit the graph action in
Bazel's remote cache with byte-identical outputs; 9.3 also acquired cached runtime
archives with all downloader URLs blocked.

The ASP.NET distribution also passed a bounded HTTP app/test compiled by SDK
**9.0.318**, running on **9.0.20**, and on **10.0.12** with `RollForward=Major`.
CoreCLR-only and default cross-major hosts were rejected. Metadata selection excludes
composite runtimes and targeting packs; incomplete ASP.NET layouts fail.
A separate source directory/output base recovered the whole graph action, then
ran the web app. Forced project recovery returned three hits / zero compilations
and byte-identical outputs. Metadata-free cached acquisition passed with downloader
URLs blocked on 9.3.

The following 25 analysis/integration checks and 17 SDK/runtime repository controls
passed on Linux ARM64. Integration suites cover both **8.8.0 / 9.3.0**:

```sh
RUNTIME_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test //tests/analysis/... \
  //tests/integration:{aspnet_runtimes,runtime_locks,sdk_locks,quickstart} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

Scope: small managed fixtures, fresh output bases on one host; no new workload,
worker, additional-platform or source-built qualification. Other shared frameworks
need a complete declared layout. See
[runtime configuration](api.md#runtimes).

## Graph inputs

`//tests/integration:preparation` passed on Linux ARM64 / Bazel 8.8.0 and 9.3.0:
multi-root sync shares one offline Restore process and shared dependency walks,
retains authored root Restore hooks, builds both apps and preserves contracts on
failure. Sync controls also cover escaped/per-root properties, locked-mode isolation
and all-framework Restore. Compiler qualification retains the full private SDK
Build with up to four nodes, bounded by available CPUs. Serial/parallel controls
cover multi-targeting, implementation/reference assembly selection, XML copies and
byte-identical declarations; see [measurements](performance.md#parallel-compiler-qualification).

`//tests/integration:cached_sync` covers declared-source preparation, cached checks,
source/membership/producer/props/mapping invalidation, SDK-selected implementation
references, package inventories, runnable output and failure/publication guards.
The prepared contracts match ordinary sync. Pins: Linux ARM64, SDK 10.0.400,
Bazel 8.8.0 / 9.3.0. Directory producers materialize sandbox-projected files;
authored file/directory links remain rejected. Shell-task controls pass during
qualification and ordinary graph builds, with explicit SDK/system tool paths.
Independent four-project, runtime-bootstrap and 543-configuration managed consumers
passed strict-lock sync/check with fresh output bases and the producer stopped:
all recorded spawns were remote hits, with no qualification execution. See
[cached preparation](performance.md#cached-preparation); remote execution remains
unqualified.

The runtime preparation drivers now declare authored snapshots, native locks and
implicit analyzer configuration; SDKs and generated reference/targeting layouts
remain separate artifacts. A 32-configuration Pipelines slice matches ordinary
sync through body/API, props, mappings and lock-byte edits and original-state
remote recovery. The six-test JIT graph also matches ordinary sync: a live runtime
reference-assembly API edit requalifies, an unchanged check reuses preparation,
and restoring the producer recovers the original result and reference DLL bytes.
All six upstream tests execute successfully with test-result caching disabled.
Scope: Linux ARM64, SDK 10.0.400, Bazel 9.3.0.
Full managed preparation also matches retained ordinary declarations byte-for-byte.
The current runner also passed independent live runtime/JIT recovery: a relocated
consumer with fresh output bases, strict module locks and the producer stopped
recovered preparation with **227 remote spawn hits / zero executions**. All five
native producers and the managed graphs recovered remotely; all six JIT tests
executed. Forcing JIT project recovery then produced **9 hits / zero compilations**
and six more actual test executions. Outputs, modes, runtime host and reference
assemblies match the producer and retained raw-qualified control. The handoff uses
`runtime_jit_public_consumer.py --preparation-base=BASE` to retain exact authored
sync sources, executable modes and module locks; no outputs or local caches transfer.

`bash scripts/bazel.sh test //tests/integration:source_globs --test_output=errors`
passed on Linux ARM64 with 8.8.0 / 9.2.0: method-body output changes, addition/removal/
rename guards and resync followed by app/tests. Sync controls cover exclusions,
hidden files, symlinks and framework-specific inputs. See [sync](api.md#sync).

`//tests/integration:dynamic_sources` and `:recursive_sources` passed 8.8.0 / 9.2.0:
flat/recursive Compile globs accept add/remove/rename/empty sets without sync or
another Restore action, with fresh sandbox output parity. Recursive globs cover new
subdirectories. Root patterns and ordinary `bazel-*` filenames inside source
directories also passed. Body edits reuse three evaluations with one project miss/two
hits; membership resets evaluation and retains conservative consumer keys. Guards
reject excluded/generated/package-crossing members, stale definitions and task-created
membership. Default unprepared actions also passed. With
`DYNAMIC_SOURCE_CACHE_URL=http://cache:8080`, 8.8.0 / 9.2.0 recovered Restore through
Bazel and all three projects through HTTP in a fresh output base, with identical app
outputs. Scope: a small managed fixture, one Linux ARM64 host; no large-graph or
independent-machine qualification for dynamic membership.

<a id="traversal-projects"></a>

Traversal coordinators keep Restore state without emitting assemblies. Sync rejects
dynamic skipping, per-reference target overrides and `TraversalPublishGlobalProperties`;
use conditional references and explicit graph properties. NoTargets requires reviewed
tasks and declared `outputFiles`; its fixture qualifies Build, not arbitrary side effects
or Pack/Publish pipelines.

IL requires locked native ILAsm/ILDasm packages; the fixture uses `IlasmFlags=-DET`.
Without a reference assembly, consumers hash its implementation. Arcade requires
its implicit packages and explicit version/repository inputs. Official/shipping builds
need `OfficialBuildId`; cold Pack uses a packable root with
`GeneratePackageOnBuild=false`. The fixture disables SourceLink/test-framework defaults;
ambient Git, Helix and full native Arcade orchestration are unqualified.

## Source toolchains and NativeAOT

The coarse qualification producer rebuilt the pinned .NET 10 VMR on Ubuntu
26.04 ARM64 / Clang 18.1.8 / Bazel **9.3.2**, producing SDK **10.0.100** and
Core/ASP.NET runtimes **10.0.0**. Its controller remains SDK 10.0.400; the upstream
bootstrap SDK and source-built bootstrap artifacts are declared inputs. The
captured native root matches its sealed-root preflight, and actual C/C++ compiler
logs select LLVM 18. This is qualification tooling, not a general SDK source rule.
The [native prerequisite overlay and sealed-root probe](../tests/source_sdk/native_overlay/README.md)
record the Ubuntu 26 / LLVM 18 package identities and observed root hash.

After stopping the producer, a fresh read-only consumer recovered the complete
`SourceSdkBuild`, SDK layouts and graph actions from HTTP with the same SDK archive
hash. Body/API edits and a forced smoke test executed without rebuilding the SDK.
The consumer made **zero PUTs**, and cache bytes stayed unchanged. A separate cold
consumer against the pinned SDK 11 migration candidate also passed Pack,
generated-package and Razor tests, Publish/run, and SDK/runtime identity checks
using only this new archive. It needed no StaticWebAssets supplement from an older
build. [Method, pins and limits](performance.md#source-sdk-production-and-recovery)
separate production, recovery and that SDK 11-rules handoff.

The [producer](../tests/source_sdk/source_action_prepare.py),
[recovery driver](../tests/source_sdk/source_action_recovery.py) and
[consumer controls](../tests/source_sdk/consumer_scenarios.py) require their declared
bootstrap inputs. The [quick start](../examples/quickstart/README.md#source-built-sdk)
shows the public toolchain handoff, not a standalone upstream bootstrap recipe.
This ARM64 evidence qualifies local production and same-host recovery; native x64
production is covered separately below. Older-glibc deployment, signing and full
upstream test parity remain unqualified. The product remains
.NET 10; using SDK 11 rules does not turn it into an SDK 11 source build.

### Native Ubuntu 26.04 x64 SDK

The coarse producer also passes on native Ubuntu **26.04 x64**, Clang **18.1.8**
and Bazel **9.3.2**, at rules revision
[`de47cfe1df06e6ec82d14aff56425af6e6227b93`](https://github.com/keegan-caruso/msbuild-bazel/commit/de47cfe1df06e6ec82d14aff56425af6e6227b93).
It builds VMR `b0f34d51fccc69fd334253924abd8d6853fad7aa` into SDK **10.0.100**
and Core/ASP.NET runtimes **10.0.0**, with reported RID `ubuntu.26.04-x64`.
The [recipe](../tests/source_sdk/LINUX_X64.md) and
[x64 input pins](../tests/source_sdk/pin-linux-x64.json) separate the SDK 10.0.400
controller, upstream RC bootstrap SDK and previously source-built bootstrap input.
Connected Restore runs the pinned VMR's unchanged bootstrap project to generate
its portable bootstrap; its resolved inputs and generated digest are recorded
before the network-isolated source action. Bootstrap generation uses the unchanged
VMR project; the source build retains the reviewed
[IdentityModel version patch](../tests/source_sdk/patches/identitymodel-file-version.patch).

A fresh output base starts with `test //:smoke`, using the source producer in the
execution configuration consumed by SDK layout. Real `cquery`/`aquery` established
that path; the execution log contains exactly **one uncached `SourceSdkBuild`**.
The net10 smoke test executes, then generated-package consumption (expected `42`),
Razor HTML generation and Publish/run (`SOURCE_SDK_PUBLISH`) pass with the same
workspace, startup options and output base. Package and Razor tests are forced;
all three scenario graph actions execute with no further source build. SDK/runtime
versions and x64 ELF product members are checked against the exported archive.

| Native product | Archive bytes | SHA256 |
| --- | ---: | --- |
| Smoke-first direct producer and consumers | 578475269 | `1ead53dd86c9cf61fdeff9836e618b2fddb555ac0df5547f8f89203a71caff4c` |
| Earlier source producer, verified by a separate exact-archive consumer handoff | 578486969 | `e4415b51444d2c85652f6e061f31c001cdd77e9f60e2bc9548167c8f50abb924` |

The earlier product at rules revision `b26d759cc0abde7e9e0365742e2eb943db958d37`
also passes smoke, generated-package/Razor and Publish/run with the archive declared
as an input and zero source actions in the handoff fixture. Both products, compact
receipts and bounded compressed build logs were exported and hash-verified.
The two archive identities are separate observations; no byte-reproducibility or
speedup claim follows from these runs.

Prerequisites include host GCC/G++ for Bazel launchers, pinned bootstrap tools,
Python/`dpkg-deb`, a case-sensitive build filesystem, nested namespaces and the
catalogued Ubuntu native closure. The explicit `--system-bwrap` path requires
root-owned packaged Bubblewrap **0.11.1-1ubuntu0.3**, generic amd64 executable
SHA256 `523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6`,
matching its declared input. Same-version optimized `amd64v3` bytes are different.
The source build keeps the declared read-only root, capability drops and network
separation; acquisition needs connected feeds before that boundary.

The SDK root declares accounts for root (UID/GID 0) and an ordinary builder
(UID/GID **1000**), with `/tmp` as home. Sealed preflight and the source script
reject unresolved caller IDs before Restore, preserving the caller's namespace
mapping. Qualification uses UID/GID 1000; arbitrary host UIDs are unqualified.
Missing-account and stock/local-feed controls establish the resolver dependency;
portable declaration/rejection checks run with
`python3 -m unittest discover -s tests/tooling -p test_sdk_accounts.py`.

Scope is this coarse native producer and local consumers on Ubuntu 26.04 x64.
Stopped-producer HTTP recovery, component scheduling/replay, older-glibc deployment,
remote execution, signing and complete upstream test parity remain unqualified
for x64. The product is .NET 10; SDK 11 rules do not make it an SDK 11 source build.

### Historical consumers and NativeAOT

Earlier Bazel 9.2 component consumers used an Ubuntu 22.04 source build and an
explicit StaticWebAssets supplement from its component bundle. The
[component producer](../tests/source_sdk/component_graph_prepare.py) and
[pins](../tests/source_sdk/pin.json) retain that historical scope. A separate
Bazel 9.3.2 retained-archive consumer control also passed;
[its results](performance.md#retained-source-sdk-consumer-recovery) do not substitute
for the new producer qualification above.

Graph NativeAOT Build/Publish/run, body edits and missing-compiler rejection passed
on Linux ARM64. Independent recovery had one project hit, zero compilations,
identical ELF bytes and a fresh successful Bazel test. This qualifies downloaded
AOT packs and declared native tools, not a source-built AOT compiler or RBE.
Drivers: [SDK consumers](../tests/source_sdk/consumer_scenarios.py),
[NativeAOT](../tests/graph_build/native_aot.py) (`--help` lists inputs/phases).

## Runtime and cache evidence

Runtime and source-SDK native qualification use the same
`tests/runtime/NativeBuild.cs.txt` driver. SDK components select SDK archive/layout
outputs through paired `--sdk-archive` / `--sdk-layout` arguments; other producers
retain their archive/product outputs. A bounded Ubuntu 26.04 ARM64 / SDK
**11.0.100** comparison against both pre-consolidation drivers passed 26 real
Bubblewrap controls: byte-identical evidence/product archives, SDK layout bytes
and executable mode, bootstrap/dependency staging, script overrides, stdout/stderr,
process/product failures and scratch cleanup. Both declared and packaged launchers
passed; the shared SDK path also passed the packaged-launcher handoff. These
small producer controls do not requalify a full upstream runtime or SDK build.

The native qualification driver's explicit `--system-bwrap` handoff checks
root ownership with Linux `statx`; it does not execute or trust `/usr/bin/stat`.
The launcher and `/`, `/usr`, `/usr/bin` must remain non-symlinks, root-owned
and not group/other writable; the launcher must be executable and match the
declared SHA-256. A compiled `NativeBuild.SelectSandbox` probe on the pinned
Ubuntu 26.04 ARM64 image / SDK **10.0.400** passed same-byte selection and
wrong-digest rejection while `/usr/bin/stat` was a symlink to Rust coreutils.
Reproduce by compiling `tests/runtime/NativeBuild.cs.txt` with a harness that
calls `SelectSandbox` on a copy of `/usr/bin/bwrap` and then a different file.
This selector-only probe is separate from the native x64 product qualification below.

The managed runtime fixture covers **260 project paths / 543 configurations /
481 compilations / 39 roots** on Linux ARM64 / Bazel 9.2.0. Earlier producer and
independent consumer runs passed **118,952 tests, 64 skips, zero failures** with
matching normalized outcomes. This is a selected graph, not the entire runtime repo.

Complete compiler inventories match raw compiler sets: LINQ body/API edits compile
**1 / 47** projects and match all **2,814 required DLL/PDB/resource files**. Generic
sync captures all **2,970** qualified project compiler selections without hand-authored
compiler/copy maps; its body/API and 481-hit local recovery checks preserve byte parity.
Native suites `resolved_inputs`, `resolved_package_copies` and `resolved_il_sdk`
passed 8.8.0 / 9.2.0, including multi-target selection, implementation references,
package basename collisions and transitive copy refresh. Twenty sync controls reject
conflicting selections, undeclared consumer inputs, input mutation and unsafe outputs.

Sync snapshots static implementation roles before the private SDK Build and
assigns analyzer roles only to actual direct graph edges. The native
`resolved_inputs` suite passes 8.8 / 9.3 on Linux ARM64: late bookkeeping adds no
edge, outer dispatch stays intact, and a generator body edit rebuilds both inner
consumers. Body/API, implementation and explicit tool controls retain fresh bytes.
Run `bash scripts/bazel.sh test //tests/integration:resolved_inputs --test_output=errors`.

The `restore_inputs` integration suite passes 8.8 / 9.3 on Linux ARM64: a
build-only producer API edit recompiles the consumer without Restore. `Exists()`
and globs retain layout, Restore outputs match conservative inputs byte-for-byte,
and fresh compilation matches. Ordinary `inputs` retains byte invalidation. Run
`bash scripts/bazel.sh test //tests/integration:restore_inputs --test_output=errors`.

Normal Bazel remote-cache recovery hits both Restore and graph actions on a fresh
consumer. Forced project recovery with a stopped producer also passed: complete
inventories yielded **481 hits / zero compilations**, with all **9,972 retained
files** matching bytes/modes. Traversal, NoTargets, Worker, IL and Arcade fixtures
passed independent HTTP recovery on 8.8.0 / 9.2.0 with Bazel action caches disabled.
Missing blobs rebuild; corruption fails. Warm local builds alone do not prove recovery.
See [performance and reproduction](performance.md).

### Unchanged JIT tests

Six authored runtime v10.0.0 tests pass on Linux ARM64, four CPUs / 6 GiB,
SDK **10.0.400**, Bazel **8.8.0 / 9.3.0**, running on source-built corerun:

| Project | Behavior |
| --- | --- |
| `CodeGenBringUpTests/Add1_ro` | Arithmetic |
| `CodeGenBringUpTests/Switch_ro` | Control flow |
| `CodeGenBringUpTests/FactorialRec_ro` | Recursion |
| `CodeGenBringUpTests/ArrayExc_ro` | Exception handling |
| `Generics/ConstrainedCall/vt1_cs_ro` | Constrained generic calls |
| `Directed/PREFIX/PrimitiveVT/callconv1_PREFIX_cs_ro` | Cross-assembly value-type calls through `helper.csproj` |

Bootstrap and test graphs use public NuGet update/check, sync/check and generated
`app_graph`. Reviewed mappings declare custom targets and deployment outputs;
sync captures the wrapper generator's implementation edges. All **36 DLL/PDBs**
and **69 deployed package files** match native raw bytes. All six raw binaries
also execute with the installed SDK absent. A body edit requires **eight hits / one
compilation**; a fresh generator edit requires **two hits / seven compilations**.
Success/failure codes **100 / 101** are preserved; omitted reference or helper producers fail.
Thirty-six sync controls cover tree bytes/membership, symlinks, collisions and
artifact-only outputs.

Helper body/API edits both produce **seven hits / two compilations** and refresh
the deployed helper. Public sync with `--compiler-references` qualifies the helper
and consumer bindings: upstream disables reference assembly emission, and Csc selects
`helper/helper.dll`. Its implementation bytes correctly invalidate the consumer.
Other custom test targets retain conservative boundaries. Restoring the authored files
recovers all nine projects and the exact original outputs.

A fresh relocated consumer, with the producer stopped and action/disk/test caches
disabled, recovered **nine HTTP project snapshots / zero compilations** and
actually executed all six tests. Compiled, deployed and runtime bytes/modes match.
The closed source-only input bundle is **27 MB**; SDK/packages come from declared
repositories. The ordinary SDK deployment project reruns when Bazel's action cache
is disabled and emits no assembly; its whole action remains cacheable by Bazel.

Reproduce with the pinned source archive/feed and declared source-runtime products:

```sh
python3 tests/graph_build/upstream/runtime_jit_public_prepare.py \
  SOURCE_ARCHIVE OUTPUT --source-products=SOURCE_PRODUCTS \
  --seed-report=PRODUCER_SEED --host-space-path=HOST_BIND \
  --cases=tests/graph_build/upstream/runtime_jit_cases.json --compiler-references
python3 tests/graph_build/upstream/runtime_jit_raw.py \
  SOURCE_ARCHIVE PINNED_FEED SOURCE_REFS RAW_RESULTS \
  --native-inventory=OUTPUT/workspace/nuget.lock.json \
  --cases=tests/graph_build/upstream/runtime_jit_cases.json
python3 tests/graph_build/upstream/runtime_jit_public.py OUTPUT/workspace RESULTS \
  --output-base=OUTPUT/bazel --raw=RAW_RESULTS/workspace --host-space-path=HOST_BIND
```

For independent recovery, run `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json
FRESH`, relocate it, stop the producer, then run the qualifier on `FRESH/workspace`
with `--seed-report=FRESH/seed.json`, a fresh `--output-base`, and the host-space bind.

Set `RULES_MSBUILD_PROJECT_CACHE_URL` to the HTTP cache. `PRODUCER_SEED` carries
the source-product archive hash. The owned root props resolve reference inputs
relative to the workspace, including private sync builds; authored test projects
stay unchanged. A fixture-only NuGet source mapping selects `dotnet-public` for
`Microsoft.Diagnostics.NETCore.Client`, avoiding differently signed copies from
racing feeds. Raw preparation uses native extraction of signed packages. Reports stay outside Git; these are correctness controls, not paired
performance measurements. Scope: these six tests and one helper dependency, not complete JIT
suites/stress, other architectures or RBE.

Inspect the authored SDK boundary with `runtime_jit_reference_probe.py RAW_RESULTS
SDK_ROOT REPORT.json`. It rebuilds the helper and consumer using the raw control's
properties, then checks reference-emission settings and `ReferencePathWithRefAssemblies`.

Runtime demo input checkpoints preserve declared ordinary file permissions and
internal hardlinks across extraction, including group-write bits. Secure extraction
still checks paths and links and removes special permission bits; the manifest
checks content, membership and modes. `test_runtime_demo_setup.py` passes all 11
controls on Ubuntu 26.04 / Python 3.14.4 under umasks `022`, `002` and `077`, including
ordinary-mode tampering, special-bit stripping, traversal and symlink rejection.

### Complete source-runtime product

For the generated net10 app, a newer bootstrap SDK selects its net10 targeting
pack versions from its bundled SDK properties. The application graph declares
only the matching packages from the verified NuGet lock and records their archive
hashes in its contract. Portable controls cover selection, the SDK 10 no-package
path and rejection of mismatched or ambiguous inputs. The complete SDK 11
bootstrap workflow also passes the product checks below.

The [source-to-app workflow](../examples/source-runtime-app/README.md) acquires the
pinned source and bootstrap SDK, updates packages, qualifies the graph, and builds
an app plus `//:runtime_package`. Its optional Apple guest cache relay is configured
when the worker is created, as described in the workflow guide. On Apple silicon,
`--worker-memory-gib` selects worker memory at creation (default 8 GiB). For SDK 11, explicitly select
12 GiB: the 8 GiB qualification attempt exhausted guest memory. Portable controls
check option validation, saved identity, worker resource matching and container arguments:

```sh
python3 scripts/setup-source-runtime.py OUTPUT --worker-memory-gib 12
bash OUTPUT/run.sh --describe-runtime --verify-product
```

A 2 CPU / 512 MiB Apple ARM64 guest transport probe checked the mounted socket,
relay restart and repeated startup, and an HTTPS cache status request with TLS
verification. This probe did not build a source runtime or qualify cache recovery.

Upstream MSBuild selects **172 managed assemblies**. Declared native producers add
**16 runtime files**, including globalization, network security, standalone GCs,
debugging libraries and `createdump`. The archive retains upstream licenses and
records source, SDK, toolchain and graph identities. This is an unsigned IL
developer runtime; official signing, ReadyToRun and release-pack parity are outside
this workflow.

The pinned runtime source preparation applies one reviewed linker adaptation before
input discovery: `StringBuilder.Append(new string(character, count))` becomes
`Append(character, count)` under its existing positive-count guard. SDK 11's CA1830
analyzer rejects the temporary allocation. The original file hash is checked before
adaptation, and resume compares against the same transformed archive bytes;
unrelated source edits remain rejected. Analyzer and warning policies remain enabled.
This source compatibility change does not by itself qualify a complete SDK 11 build.

Current producers require native Ubuntu 26.04 ARM64 or x64 and explicitly select
LLVM/Clang 18.1.8 for CoreCLR, native libraries and the host. The declared native
package root links against glibc 2.43; deployment on older-glibc distributions and
RBE remain unqualified.

The [source-SDK producer](#source-toolchains-and-nativeaot) is separately qualified
on Ubuntu 26.04 / LLVM 18. Historical SDK archives, the separate NativeAOT
compiler/catalog and manual Linux CI retain their original Ubuntu 22.04 / LLVM 14
pins where declared; those results are not relabeled as Ubuntu 26.04 qualification.

The declared-environment probe passed in a six-GiB ARM64 guest: all 194 packages
assembled, and C/C++ compiled, linked and ran inside the bubblewrap root. The
root reported Ubuntu 26.04, Clang 18.1.8 and GNU coreutils 9.7. Reproduce with
`python3 tests/runtime/environment_probe.py FRESH_OUTPUT --source-archive PINNED_SOURCE`.
This checks toolchain closure and compiler selection; the full runtime product
requires the separately budgeted source-to-app workflow above.

Native Ubuntu 26.04 x64 qualification at rules revision
`7e82ad6fe3d19e22be67c569a2c493ed1a785585` built the same pinned runtime
**10.0.0** source (`60629d14374c56f1cb51819049ad1fa529307f8d`) with bootstrap
SDK **11.0.100**, Bazel **9.3.2** and declared Clang **18.1.8**. All three native
producers and the managed graph (**631 configurations / 563 compilations**,
121 package archives / 320 native locks) built successfully. An outer job deadline then
interrupted verification; resuming the same owned setup completed both forced
product tests (**2/2**), including all **172 managed framework members**,
producer hashes/modes, archive comparison, SDK-absent execution and the
missing-CoreCLR control. The exported `runtime-linux-x64.tar.gz` has SHA256
`08199700d6f2e5c2bf32c7d3b32ef2294f26adcd4504f8ecb10d828ce92e28f6`.
This is same-host build/resume/product qualification, with local action reuse
in the final verification. It does not establish independent x64 remote recovery,
a cold-build timing or full upstream test parity. Source-built x64 SDK
qualification is [separate](#native-ubuntu-2604-x64-sdk).
ARM64 worker/default release gates retain their separate qualification scope.

The native x64 invocation is documented in the
[source-to-app guide](../examples/source-runtime-app/README.md#native-linux-x64).
On Ubuntu hosts with path-bound Bubblewrap AppArmor policy, `--system-bwrap`
requires the exact generic **amd64** `0.11.1-1ubuntu0.3` launcher bytes locked in
the catalog. Ubuntu may instead install optimized **amd64v3** bytes at the same
package version; version equality is insufficient. The qualification installed
the verified generic package, preserving AppArmor policy and exact digest checks.
Host GCC/G++ are also prerequisites for Bazel tool-launcher analysis
(`rules_pkg` / `rules_cc` local C++ configuration); native payload compilation
still uses declared Clang and the declared tool filesystem. The qualification
controller used a six-CPU quota / 22 GiB memory cap, .NET capped at four CPUs,
native `-numproc 4` and final Bazel `--jobs=1`. These are run budgets, not
verified minimum requirements.

The official workflow with SDK **11.0.100** passes on Ubuntu 26.04 ARM64,
four CPUs / **12 GiB**, Bazel **9.3.2** and Apple Container **1.7.1**
(initializer **0.54.0**). It compiled the managed graph, assembled the runtime
archive and actually executed both product tests. The retained host launcher also
verified all 172 source-framework members. The exported archive contains 649
verified file hashes/modes and has SHA256
`aaecfc189f42d0793acc273199ad50d46aa873b765ad4d21741291df27bf3f3f`.
Qualification and some build actions were recovered from cache; this is a complete
product check, not a cold-build measurement. No guest OOM events occurred.

With that producer stopped, a fresh consumer on a separate Mac passed the official
read-only workflow. A second fresh output base recovered all three graph actions,
Restore, all three native producers and native version generation from the remote
cache. Toolchain package extraction was prepared separately; the runtime build
then prohibited cache misses. Both product tests actually executed, all 649 file
hashes/modes and the archive matched the producer, and the retained host launcher
passed. Across the complete consumer and verification window, the unchanged cache
server recorded 27,622 additional GETs and zero completed PUTs. These are correctness
results, not a paired timing comparison. Both Apple hosts used Container 1.7.1
and initializer 0.54.0.

Earlier, the full Ubuntu 26.04 ARM64 workflow passed on four CPUs / 8 GiB, SDK
**10.0.400** and Bazel **9.3.2**. It built CoreCLR/JIT, native libraries and the
host with Clang **18.1.8**, then built the managed graph with **563 misses / zero
project-cache hits**. Both `//:app_test` and `//:runtime_test` actually executed:
172 source-framework members, producer hashes/modes, archive contents, SDK-absent
execution and the missing-CoreCLR negative control passed.

A host/service interruption stopped the first final managed Build. Supported
`--resume` reused the same owned setup and accepted the completed native outputs
from cache, then completed managed Build, packaging and forced tests. The exported
22 MiB archive has SHA256
`5bc7ec87952a0062eaaf991e7a04fd8b090e4f73c95139d7ea96db2a71d0d3a6`.
This is local product/recovery qualification, not stopped-producer remote recovery
or a paired performance result. [Phase observations](performance.md#source-runtime-product)
keep qualification, resumed managed execution, Restore and tests separate.

The earlier public setup passed in a fresh pinned Ubuntu 22.04 ARM64 container, four CPUs /
8 GiB, SDK **10.0.400**, Bazel **9.3.0**. Setup used a pinned source archive and
prebuilt image. SDK/tool and package acquisition ran in the new container, with HTTP action
and project caches available. Public update/check and sync/check qualified
**631 configurations / 563 compilations**, 119 package archives and 320 native
lockfiles. Native producers built CoreCLR/JIT, five libraries and three host files;
the managed graph recovered 563 projects from the project cache.

Bazel actually executed `//:app_test` and `//:runtime_test`: all 172 framework names
load from the source product, producer bytes/modes and archive members match,
SDK-absent execution succeeds, and removing CoreCLR fails. A relocated independent
container, with the producer stopped and no local action cache, recovered all three
graph actions, Restore, all three native producers and version generation through
HTTP. All **649 runtime files** and the complete archive match; both tests actually
executed again. Package extraction is the sole local build action.
A separate source-only consumer also recovered the whole `MSBuildSyncPrepare`
action with misses forbidden: 122 remote spawn hits, zero executed spawns and
byte-identical declarations. The producer was stopped; only the exact authored
sync inputs and module locks transferred.
[Timings and method](performance.md#source-runtime-product) separate setup from recovery.

The Ubuntu 22.04 results above are historical; current execution requires Ubuntu
26.04 ARM64 or x64 with nested namespaces; the Apple SDK 11 recipe above explicitly
selects 12 GiB. For compilation
with a source-built **SDK**, use the separate
[quick-start scenario](../examples/quickstart/README.md#source-built-sdk).

### Declared native preparation

Source selection, three version files, shared source archives and tool trees are
Bazel outputs. ARM64 tools come from 194 hash-locked Ubuntu 26.04 packages;
x64 uses its separate [locked catalog](../tests/runtime/native-packages-x64.json),
including the explicit compiler-rt dependency. The
[SDK catalog](../tests/runtime/native-packages-sdk-x64.json) selects its packages
independently. Both lists preserve installation order. Each entry is either a
complete package record or a reference into the [shared x64 records](../tests/runtime/native-packages-shared-x64.json).
A reference pins the name and SHA-256 of the complete record serialized as
compact JSON with sorted keys. To update one catalog, replace its entry with
the new package record. The assembler writes the expanded catalog alongside the
toolchain for provenance.

Clang, LLD and LLVM are pinned to
`1:18.1.8-20ubuntu8`; declared-root checks verify the OS and compiler before
compilation. Explicit aliases replace package scripts, including deterministic
`Etc/UTC` for `/etc/localtime`. Extraction still uses the qualified host's
`dpkg-deb`; native compilation uses the declared tool filesystem.

Historical `//tests/integration:native_preparation` controls passed Bazel 8.8 /
9.3 with the earlier Ubuntu 22.04 toolchain: suffixless source URLs, body/version
invalidation, Brotli's nested BUILD file, failed-build recovery
and link-preserving archives. All 7,806 source/version members match the previous
input archive in bytes, link targets and executable modes. On both pins, fresh
output bases recover expanded SDK/source repositories with the downloader disabled,
the source archive absent and both action caches disabled. A separate 9.3 control
with isolated local repository caches recovers them through the experimental HTTP
repository-contents cache; an actually executed action reads matching SDK/source
bytes. This qualifies these repositories, not general remote execution. Build the three
producers with `//native:{runtime_coreclr,runtime_libraries,runtime_host}`.

### Connected source-runtime workflow

Set `RULES_MSBUILD_PROJECT_CACHE_URL` to the HTTP cache. Prepare from the pinned
runtime source archive and declared native tools:

```sh
python3 tests/graph_build/upstream/runtime_checkout_prepare.py SOURCE_ARCHIVE PREPARATION \
  --toolchain=NATIVE_TOOLCHAIN_TAR --toolchain-sha256=TOOLCHAIN_SHA256 \
  --sandbox=BWRAP --sandbox-sha256=BWRAP_SHA256 --host-space-path=HOST_BIND
```

This runs public NuGet update/check and sync/check for the **543-configuration /
481-compilation** managed graph, generates five native producers, then syncs the
six-test JIT graph. Explicit framework mappings assign linker outputs to inner
nodes. A two-framework SDK control checks ownership against actual Build outputs.

Version inputs come from authored `eng/Versions.props`, native templates and the
pinned commit; components preserve those generated bytes. All five native archives
reproduce the qualified inputs byte-for-byte, including member order. Native
compiler/OS tools use a supplied, hashed bundle.

Preparation requires the qualified Linux ARM64 container with nested namespaces,
Python, download access and 12 GiB physical host headroom. `--resume` validates
input identities and skips completed stages. Immutable native archives are linked
within the owned preparation when possible. The fixture pins
`Microsoft.TestPlatform.ObjectModel` to `dotnet-public` to avoid signed-archive
ambiguity across upstream feeds.

No previous qualified workspace, compiled products archive or generated headers
are required. `OUTPUT` below means `PREPARATION/jit`. An existing producer can
still be connected with
`runtime_jit_public_prepare.py SOURCE_ARCHIVE OUTPUT --source-producer=WORKSPACE
--cases=tests/graph_build/upstream/runtime_jit_cases.json --compiler-references
--host-space-path=HOST_BIND`.

The generated test module binds `@jit_source_runtime//:references` into sync and
uses `@jit_source_runtime//:host` for execution. The producer's generated managed
graph, five native producers and package deployment form normal Bazel dependencies.
`bazel test //:jit_tests` builds/reuses that closure; there is no intermediate
`source-products.tar.gz` or hash-report handoff. Public update/check and sync/check
pass; compiled and host bytes/modes match the raw-qualified bounded control.

A fresh relocated Bazel 9.3 consumer, with the producer stopped, remotely recovered
Restore, managed graphs and all five native actions, then **actually executed all
six tests**. Forcing only the JIT graph action recovered **nine HTTP project
snapshots / zero compilations** and executed the tests again. Outputs, the
reference tree and runtime bytes/modes match the producer.

Reproduce with `runtime_jit_live.py OUTPUT RESULTS --output-base=OUTPUT/bazel
--bounded-seed=BOUNDED_RESULTS/seed.json --host-space-path=HOST_BIND`. Close inputs
with `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json FRESH`, relocate to
another machine, stop the producer, then run `runtime_jit_live.py FRESH RESULTS
--output-base=FRESH_BASE --seed-report=FRESH/seed.json --host-space-path=HOST_BIND`.

Connected edits rerun all six tests against the refreshed runtime:

| Edit | Runtime compilations | JIT compilations | Native actions | Restore actions |
| --- | ---: | ---: | ---: | ---: |
| Pipelines body | 6 | 0 | 0 | 0 |
| Pipelines API | 17 | 9 | 0 | 0 |
| Native version marker | 0 | 0 | 1 | 0 |

Body edits preserve reference and JIT output bytes. Native edits change only
`libSystem.Native.so`; managed outputs stay unchanged. Restoring each edit recovers
exact original bytes/modes with no graph, native or Restore executions. A fresh
machine recovered the **API-edited** closure through normal Bazel remote caching,
with the edited-state producer stopped: zero compilations/build/Restore executions
and six actual test runs. The 138 reference files use `build_inputs`: API edits
retain the JIT Restore action. All **2,908 Restore files** match the conservative
binding in bytes and modes. These are correctness controls, not paired timings.

```sh
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py OUTPUT RESULTS \
  --output-base=OUTPUT/bazel --host-space-path=HOST_BIND \
  --case=api --close-api=EDITED_INPUTS
# Relocate EDITED_INPUTS, stop the producer; use a fresh output base:
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py EDITED_INPUTS RECOVERY \
  --output-base=FRESH_BASE --host-space-path=HOST_BIND --recover=EDITED_INPUTS/seed.json
```

Omit `--case` to run body, API and native controls in sequence.

Fresh-source preparation passes in a clean container without prior runtime
workspaces or products, followed by six actual JIT test executions. The
managed and deployed JIT outputs match the raw-qualified control. This remains a
bounded runtime/test graph: no complete repository bootstrap, official versioning
or signing, native toolchain bootstrap, other-architecture or RBE qualification.
Reports are correctness evidence, not paired timings.

`python3 tests/graph_build/worker_preparation.py` and its `--cache-mb=0` variant
passed on Linux ARM64: concurrent file/tree staging preserves bytes/modes,
rejects undeclared and overlapping destinations, detects corrupt preparation,
and clears failed/zero-budget state. Staging still uses private copies; full
prepared payload verification precedes any child workspace writes or evaluation.
`//tests/integration:{workers,evaluation_worker}` also passed all six controls on
Bazel 8.8.0 / 9.3.0, covering actual builds, body/API edits, retained evaluation,
fresh-build byte parity, failure recovery and cached/zero-budget workers.

## Project-cache publication

Use serialized publishing processes per shared endpoint/key namespace, and explicit
read-only consumers. This applies across processes, containers and hosts; a chosen
publisher host alone does not serialize its jobs. Ordinary Bazel HTTP AC does not
provide compare-and-swap publication for divergent writers. The default remains
read-write; [cache configuration](api.md#caching-and-workers) describes the
consumer flags and limits.

Native macOS ARM64 / SDK **10.0.400** controls pass with
`python3 tests/graph_build/remote_publication.py`: independent identical writers,
concurrent complete readers, serialized divergence rejection, no-PUT consumers,
failed/cancelled publication and strict option parsing. `remote.py` also passes
actual three-project HTTP recovery, read-only misses without remote repair,
eviction, interrupted downloads and corruption rejection. A native MacBook
publisher exited before an independent native Mac mini read-only consumer fetched
a fresh snapshot through the shared HTTPS service; payload SHA256 matched. This
cross-host check uses a synthetic snapshot, not a whole graph or Linux workers.
Native Linux transfer and same-host whole-action recovery passed the
[Linux x64 controls](#native-linux-x64-controls). Whole-graph cross-host recovery
remains unqualified.

## Linux worker qualification

Ubuntu 26.04 ARM64, SDK **10.0.400** and Bazel **9.3.2** pass the cached and
zero-budget worker fixtures plus retained evaluation: actual Build/Publish byte
parity, body/API edits, failed compilation and clean retries. Forced worker tests
passed **2/2** (105.1 / 104.4 seconds); retained evaluation passed in **75.8 seconds**.
The fixture checks the exact private worker HOME/application-data layout and
per-project working directory, with a positive proof that the worker branch ran.

Actual Linux process controls pass bounded noisy output, active deadlines,
cancellation, descendant cleanup and retained-protocol rejection. The real broker
also passes live cancellation, failed-output publication isolation, fresh retries,
private-input exclusion, idle-crash lease reclamation and normal-exit cleanup. Its
controlled child replaces MSBuild; this does not qualify cancellation initiated by
Bazel during every staging/publication phase. Synchronous filesystem operations
remain noninterruptible. Publication-queue controls verify bounded concurrency and
draining after capture/publication failures separately.

`//tests/integration:worker_defaults` passes in **62.2 seconds**: an unforced Build
uses the actual Bazel worker runner on the qualified execution platform, then a body
edit reuses two projects and recompiles one. Target-only declarations, explicit
worker/stable-path opt-outs and ordinary Restore/Pack/Publish remain non-worker;
explicit worker Publish remains selectable. Existing generated wrappers need a sync
rerun to adopt [automatic defaults](api.md#caching-and-workers).

These are small correctness controls with a four-CPU/six-GiB guest, two Bazel jobs,
one local test and one worker. The qualification copy explicitly applies those
nested resource limits; test expectations are unchanged. The
[SDK 11 platform matrix](#sdk-11-platform-qualification) records the corresponding current
worker checks. ARM64 evidence does not qualify x64, macOS workers or RBE.
Run the portable and broker controls via
`python3 tests/graph_build/acceptance.py OUTPUT --linux-workers` after building the
runner in the qualified ARM64 environment.

## Bounded native regression controls

Project-cache payload transfers use 64 KiB buffers and one transfer budget per
store (default eight), including concurrent project requests. Uploads first verify
private staged payloads; retries reopen those verified bytes. Downloads verify
streamed digests before publication, retain disk verification and deduplicate shared
payloads. Small protocol manifests remain buffered. Graph snapshot capture stays
serial while up to two immutable publications overlap capture; all started
publications finish before the invocation succeeds or reports failure. This does
not change the serialized-publisher policy above.

Worker child and retained-engine invocations have a one-hour active deadline.
Cancellation terminates their process trees and retires retained engines. Output
pipes continue draining while retaining at most 1,048,576 characters of diagnostic
tail plus a truncation marker; oversized retained replies fail. The input pump
receives cancellation while the serial executor builds and permits one queued
request. These bounds apply to child execution and diagnostics, not the complete
staging/publication lifecycle; synchronous filesystem operations are not immediately
interruptible. Native fake-child controls cover noisy/hung/failed children,
descendant cleanup, cancellation, protocol rejection and fresh retries. Actual
Linux broker cancellation is qualified above; cancellation initiated by Bazel
across the complete sandbox lifecycle remains unqualified.

Qualification shares raw content/mode observations within each before/after-Build
verification phase, preserving both existing digest encodings. It never reuses
pre-Build observations after Build. A shared immutable multi-owner path index
preserves distinct policies: qualification excludes ambiguous owners and their
consumers; execution rejects overlapping outputs. Native sync/compiler-copy,
mode/mutation and randomized ownership controls pass. Native Ubuntu 26.04 x64
with SDK 11.0.100 also passes all 63 ProjectSync controls without skips, including
seeded qualification reuse, SDK inventory preservation and overlapping-owner
exclusion; see the [platform matrix](#sdk-11-platform-qualification).

ProjectSync mapping controls reject exact duplicate JSON keys at every depth and
case-ambiguous contract fields. Shared project/framework merging retains dictionary
inheritance and whole-record document replacement; 300 baseline/current expansion
comparisons are byte-identical, and merged/explicit mappings emit identical graphs.

Graph contracts, sync inputs, worker paths, cache entries and ArtifactTools share
span-based relative-path component checks. Caller-specific character, containment
and symlink policies remain separate. Native SDK 11.0.100 differential controls
matched 10,023 paths; 10,000 repeated validations allocated 3,680,000 bytes with
the former split predicate and zero with the span scan. This measures validation
allocations only. `python3 tests/graph_build/input_integrity.py` retains edge-case,
traversal and fresh-symlink controls; isolated declared-source builds also pass.

Shared tree traversal preserves file-only output inventories and directory-inclusive
input inventories, including empty directories and ordinal producer-tree ordering.
Native SDK 10/11 controls compare all four former callers against the shared walk:
32 cases retain exact inventories, partial yields, exception types and diagnostics
for ordinary, empty, missing, linked-root and linked-child trees.

Runtime layout selection indexes tree members by selected ancestor prefixes,
retaining nested selections and member ordering. Native Bazel 9.3.2 analysis and
graph-layout controls pass. Package extraction hashes into a private staged archive,
then uses that same handle for ZIP validation, extraction and retained archive bytes;
a final source check precedes completion metadata. Native artifact controls cover
locked/generated identities, tampering, traversal, validation markers and retained
bytes. The [platform matrix](#sdk-11-platform-qualification) records native Linux
artifact controls separately; these small controls do not establish a full
source-runtime product.

Run the portable controls with the pinned SDK and fresh temporary fixtures:

```sh
python3 tests/graph_build/worker_supervision.py
python3 tests/graph_build/publication_queue.py
python3 tests/graph_build/remote_streaming.py
python3 tests/graph_build/remote_publication.py
```

The native streaming control fetches eight 8 MiB payloads with a two-transfer
budget, verifies interrupted-body recovery and one GET for shared content.
[Performance](performance.md#bounded-cache-controls) records scoped observations;
these controls do not qualify Linux workers or claim end-to-end speedups.

## Snapshot materialization defaults

Production `FileMaterializer` passed real XFS reflink and ext4 copy-fallback controls
on Linux ARM64 / SDK **10.0.400**: empty, small and multi-buffer files preserve
bytes, executable modes and timestamps; writable replays remain independent;
same-size/time corruption is rejected and the destination removed. The graph replay
suite with the default clone mode passed body/API edits, fresh-build byte parity,
Publish replay and corrupt-payload controls on XFS. Replay/body/API rows recorded
**54 / 40 / 23 actual clones**; Publish replay recorded **64**. These are small
correctness controls, not performance measurements or qualification of other filesystems.
Unsupported clones use verified private copies. Reproduce the graph controls with
`RULES_MSBUILD_GRAPH_PROFILE=1 python3 tests/graph_build/replay.py`; place `TMPDIR`
on a reflink-capable filesystem to exercise cloning. `RULES_MSBUILD_GRAPH_COPY_MODE=copy`
retains an explicit copy control.

## Limits

- Persistent workers require Bubblewrap and nested namespaces. Broad worker/remote
  release qualification remains Linux ARM64. The native x64 source-runtime run
  exercises its explicit worker strategy; automatic x64 workers, macOS workers
  and RBE remain unqualified.
- Unknown SDKs/workloads and whole-repository runtime/native build parity are unqualified.
- Custom task/analyzer/generator reads, package side effects and output ownership
  require contracts. Build compiler selections do not qualify Pack/Publish changes.
- Evaluation reuse is opt-in for reviewed compiler-only inputs. Arbitrary process,
  time or external reads cannot be safely retained. Verification still reads bytes.
- Sandboxing and graph isolation are distinct. Build trusted projects; exports reject
  links. HTTP publication has no atomic guarantee for divergent writers. Test sharding
  is unsupported.

Run suites with `bash scripts/bazel.sh test //tests/integration:SUITE
--test_output=errors`. Use fresh fixture/report directories and separate producer/
consumer containers for recovery. [Contributing](../CONTRIBUTING.md) covers tooling.
Keep reports outside Git. Earlier commands, pins and qualification details remain
in the [versioned record](https://github.com/keegan-caruso/msbuild-bazel/blob/fa2764b55f630ae0462e836aa3163b0807f07f7f/docs/support.md).
