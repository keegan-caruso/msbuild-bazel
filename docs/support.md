# Support and limits

Graph/plugin is the sole backend. Current baseline: SDK **11.0.100**, Bazel **9.3.2** only (Bazel 8.x dropped). Adapter compilation requires MSBuild 18+ and its stable `Microsoft.Build.ProjectCache` API (SDK 10+; SDK 8/9 unsupported; repository resolution controls may still use synthetic older names without compiling adapters).

`USE_BAZEL_VERSION` overrides `.bazelversion`; source-runtime setup records it and rejects resume with a different version. Historical pins below describe their original runs, not 9.3.2 qualification; release gates are tracked in [the work queue](../WORK_QUEUE.md). Distribution is a reviewed Git commit via `git_override` (no BCR release or cross-revision API/cache guarantee; see [pinning and rollback](api.md#pin-update-and-roll-back-the-rules)).

Inputs, packages, tool layouts, generated files, and output ownership must be explicit (sync does not trace arbitrary task reads or acquire missing packages).

Native macOS ARM64 (SDK **11.0.100**, Bazel **9.3.2**) passes `scripts/check.sh`, analysis/execution-requirements/version controls, and `scripts/check-dotnet.sh` (all 4 owned projects compile/format cleanly; style, tooling, artifact, and 63 ProjectSync tests with 7 Linux-only skips). Graph evaluation and Restore bind the selected SDK's `Microsoft.NETCoreSdk.BundledVersions.props` explicitly so the SDK initializes `NetCoreSdkRoot` (supports SDK 11.0.100 earlier imports; authored properties cannot override either; macOS ProjectSync passes with SDK 10.0.400 and 11.0.100, 61 tests each / 7 skips). Owned SDK bootstrap and Restore disable the CLI MSBuild server ([enabled by default in SDK 11](https://github.com/dotnet/docs/blob/main/docs/core/whats-new/dotnet-11/sdk.md#msbuild-server-enabled-by-default); disabling Roslyn shared compilation alone is insufficient; ambient opt-in cannot override).

Full native graph acceptance passes all **17 slices** and quickstart (offline package SDKs, signed archives, MTP/VSTest, tool replay, independent publication; replay fixtures make copied roots writable for temp `NuGet.Config`; default HTTP-cache fixture isolates macOS LocalApplicationData).

Historical 9.3.0 upgrade passed 29 analysis/integration checks on Linux ARM64 (8.8 compat, SDK facts, workers, compiler selections, recursive-source HTTP recovery, cached HTTPS SDK acquisition with downloader URLs blocked). Current-baseline gate:

```sh
SDK_VERSION_CACHE_URL=http://cache:8080 DYNAMIC_SOURCE_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{sdk_versions,quickstart,sdk_locks,workers,recursive_sources,resolved_inputs} \
  --test_output=errors
```

Earlier 481-compilation runtime baseline and historical source-SDK component consumers retain 9.2 qualification; downloaded-SDK runtime slice and current source-SDK producer have separate 9.3 results.

## Cache and worker diagnosis

Record exact rules commit, SDK/Bazel versions, platform, and command. Keep the first failure before retrying; use a fresh disposable output base for recovery checks; separate SDK acquisition, whole-action hits, and project snapshot hits.

| Symptom | Evidence to inspect | Next check |
| --- | --- | --- |
| Unchanged Bazel action runs again | Execution log `mnemonic`, `runner`, `cacheHit`; changed command/action env | Compare declared inputs, flags, and SDK/rules pins (a cache endpoint flag change alters the experiment). |
| Graph runs with zero project hits | Graph `report.json` hits/misses, prepared Restore, worker fields | Confirm worker selection/project endpoint; compare input bytes, Unix modes, membership, global properties, and SDK inventory. |
| Sync or Restore repeats compilation | `PROJECT_SYNC_CACHE` and `PROJECT_SYNC_RESTORE_CACHE` diagnostics | Confirm qualified execution and explicit sources; compare pre/post-build observations; restore original file mode on rollback (don't assume `0644`). |
| TLS handshake/body timeout | First client error and cache/relay connection counts | Confirm guest TLS trust and reachability, then bound concurrent connections. Keep verification enabled. |
| Worker hangs, exits or truncates output | Bazel worker log, exit/signal, bounded diagnostic tail, graph report | Distinguish request deadline, child termination, and retained-engine failure; preserve first error and retry with a fresh worker. |

For graph diagnostics, set `profile_build = True` and keep `bazel-bin/NAME.graph/report.json`, sibling binlog, and `--execution_log_json_file=PATH` (profiling adds work; overlapping phases are not unprofiled timings; remote counters count successful logical payloads only—unchanged cache size or read-only mode does not prove zero network PUTs). For sync diagnostics, set both launcher and action env:

```sh
RULES_MSBUILD_SYNC_PROFILE=1 bazel run //:sync \
  --action_env=RULES_MSBUILD_SYNC_PROFILE=1
```

Retain `PROJECT_SYNC_PROFILE` phase records from the log (launcher reads process env; cached preparation reads `--action_env`). Failure bounds (not workload budgets): worker diagnostic tail **1,048,576 chars** (drains output), worker request deadline **1 hour**, termination wait **5 s**, project-cache HTTP deadline **2 min** (including streamed reads). Keep bounded evidence bundles outside Git (pins, command, first failure + controlled retry, summaries, needed logs; separate wall time, exit code, peak memory method, and disk growth; inspect logs before sharing and exclude tokens/private cache config/full workspaces).

## Dependency updates and security triage

Maintainers own bootstrap pins, package catalogs, and optional benchmark deps: verify upstream advisory/fix, call sites, and fresh-env validation before updating; keep source-product, bootstrap, and historical measurement pins separate.

Optional benchmark env pins GitPython **3.2.1** (replacing 3.1.62, which had 7 GitHub alerts: 5 high, 2 moderate; used by pinned bazel-bench for clone/fetch/checkout). Fresh `scripts/setup-bench.sh` passed dep checks, real clone/fetch/checkout controls, and 4 owned measurement tests (does not audit arbitrary repos or guarantee zero future alerts). For release candidates, review alerts and [work queue](../WORK_QUEUE.md), run behavioral/scaffold/style gates, preserve pins/reports/limits, and publish via reviewed change.

## Shared cache on two Macs

General Apple Container wrapper defaults to pinned Ubuntu 26.04 ARM64 (`RULES_MSBUILD_CONTAINER_ARCH=amd64` for Rosetta; SDK 11.0.100 and Bazel 9.3.2 pinned independently). Extraction uses pinned `libarchive-tools` 3.8.5-1ubuntu2.3 because GNU tar fails nested extraction under Rosetta on `openat2`/`ENOSYS` ([Ubuntu bug 2166326](https://bugs.launchpad.net/ubuntu/+source/tar/+bug/2166326)); source archive creation keeps GNU tar; outside container `RULES_MSBUILD_TAR` overrides `tar` (SDK archives hash-verified first).

Fresh Ubuntu 26.04 ARM64 and AMD64 Rosetta containers passed public downloaded-SDK quickstart (sandboxed Build, test, `RuntimeInformation.ProcessArchitecture` `Arm64`/`X64`, sync `--check`; does not qualify x64 source-runtime producer or Linux workers/recovery).

Share one HTTP(S) endpoint via host env (outside Git):

```sh
# Export a reachable endpoint as RULES_MSBUILD_SHARED_CACHE_URL first.
bash scripts/run-apple-container.sh bash scripts/bazel.sh test \
  //tests/integration:quickstart --test_output=errors
```

When set, the wrapper configures guest-only Bazel defaults: same URL for action cache and `RULES_MSBUILD_PROJECT_CACHE_URL`, no disk cache, sync uploads, all downloads, 2 jobs, 1 local test, 1 graph worker (does not enable workers or change sandboxing; CLI flags override; `RULES_MSBUILD_CONTAINER_PREBUILT=1` forwarded for matching prebuilt images).

If guests cannot route directly to HTTPS, set `RULES_MSBUILD_SHARED_CACHE_SOCKET` to a running host UNIX socket forwarding raw bytes: wrapper mounts it and starts an opt-in Python 3 guest TCP relay mapping `/etc/hosts` to loopback (TLS verifies original DNS hostname without terminating TLS or URL credentials; lifetime follows disposable container).

Run one heavy container per host (default 4 CPUs / 6 GiB); check `df -h` (remote cache avoids duplicate action caches, not active outputs/SDK/package/repo space). Containers use `--rm`, keeping only `/evidence` and `artifacts/apple-container/run.*`. Recovery evidence still requires fresh bases and a stopped producer.

### Cross-host downloaded-SDK graph recovery

The [three-phase quickstart fixture](../tests/graph_build/cross_host_recovery.py) compares Bazel action recovery with MSBuild project snapshot recovery. Use the same checkout, an Ubuntu ARM64 guest on each physical host, and one reachable HTTP cache supporting both Bazel and JSON project-cache requests. Place the rules and workspace outside the sandbox’s private `/tmp`. Select a fresh nonce per run. Keep the revision, nonce and rules path identical across phases.

On Ubuntu 26.04 ARM64 / Bazel **9.3.2** / downloaded SDK **11.0.100**, a MacBook guest compiled three projects, published snapshots and stopped. Two fresh Mac mini guests read from the same frozen HTTP cache with `linux_stable_paths = True` (Bubblewrap) and workers disabled. Both executed the test and app and attempted zero PUTs.

| Consumer | Build/test wall | HTTP response-body bytes | Result |
| --- | ---: | ---: | --- |
| Bazel whole-action recovery | 127.13 s | 135,342,887 | All five build actions hit. All 82 files and 29 directories matched the producer. One GET connection was retried. |
| MSBuild project snapshots; Bazel action reads disabled | 13.75 s | 152,341 | Three project hits, zero compiler calls. All 109 replayable entries matched; the two cold `obj/*.AssemblyReference.cache` files are excluded from snapshots. |

Times are single observations with SDK downloads prepared, and exclude the subsequent app invocation. File comparisons cover bytes and modes; timing reports and binlogs are excluded. A separate control using ordinary sandbox paths missed all three projects.

For repeat runs, the Apple Container wrapper accepts a host download directory in `RULES_MSBUILD_CONTAINER_ACQUISITION`; pass `--acquisition /acquisition` to reuse verified SDK downloads in the guest. Each host can prepare its own downloads.

Run inside the producer guest and save its report before stopping the guest:

```sh
python3 tests/graph_build/cross_host_recovery.py seed /qualification \
  --rules "$PWD" --revision "$REVISION" --nonce "$NONCE"
cp /qualification/report.json /evidence/seed.json
```

Transfer only `seed.json` to the consumer. Run each command in its own fresh guest on the second host with the report at `/evidence/seed.json`:

```sh
python3 tests/graph_build/cross_host_recovery.py action /qualification \
  --rules "$PWD" --revision "$REVISION" --nonce "$NONCE" --seed /evidence/seed.json
python3 tests/graph_build/cross_host_recovery.py project /qualification \
  --rules "$PWD" --revision "$REVISION" --nonce "$NONCE" --seed /evidence/seed.json
```

## Native Linux x64 controls

Native Ubuntu 26.04 x64 (SDK **11.0.100**, Bazel **9.3.2**, 4 CPUs / 6 GiB) passed all 4 owned builds/format, 5 style, 81 tooling, 19 artifact, and 63 ProjectSync tests (0 skips), plus 9 standalone broker/publication/transfer/integrity/ownership controls and zero-budget worker preparation.

Stopped-seed quickstart consumer (fresh base, `--nocache_test_results`, same read-only project cache) recovered the graph action, ran its test, and matched all 112 output entries (bytes/modes; 498 GETs, 0 PUTs; qualifies same-host whole-action recovery only). Reproduce:

```sh
python3 tests/graph_build/linux_action_recovery.py /tmp/action-recovery \
  --rules "$PWD" --bazel "$PWD/.tools/bin/bazelisk" \
  --expected-revision "$(git rev-parse HEAD)"
```

Cache-reuse fixtures previously assumed mode `0644` (failing under umask `002`); restoring each file's starting mode passes under `022`, `002`, and `077` (SDK inventory unchanged). Standalone controls (after Release-building `GraphBuild` and `ProjectSync` with `RULES_MSBUILD_DOTNET_ROOT`):

```sh
for test in worker_supervision worker_preparation publication_queue worker_lifecycle \
  remote_streaming remote_publication remote input_integrity output_ownership; do
  python3 "tests/graph_build/$test.py"
done
python3 tests/graph_build/worker_preparation.py --cache-mb=0
python3 -m unittest discover -s tests/project_sync -p test_sync.py -v
```

## SDK 11 platform qualification

SDK **11.0.100** / runtime **11.0.0** and Bazel **9.3.2**:

| Environment | Observed scope |
| --- | --- |
| Native macOS ARM64 | Owned build/format/tests, all 17 graph acceptance slices, Bazel quickstart test. |
| Ubuntu 26.04 ARM64, 4 CPUs / 6 GiB | Owned checks (all 61 ProjectSync controls at that rev), real broker lifetime/prep, cached/uncached workers, evaluation worker, quickstart, automatic worker defaults (body edit: 2 hits / 1 compile). |
| Ubuntu 26.04 AMD64 under Rosetta, 4 CPUs / 6 GiB | Prebuilt toolchain image, public quickstart sync/check, greeting, forced executable test. |
| Native Ubuntu 26.04 x64, 4 CPUs / 6 GiB | Full owned gate (0 skips), 9 broker/transfer/input controls, stopped-seed fresh-output HTTP graph recovery with forced test and 0 consumer PUTs. |
| Ubuntu 26.04 ARM64 dotnet/runtime graph, 4 CPUs / 12 GiB | Official source-to-app setup, managed compilation, runtime packaging, 2 forced tests, retained host launcher (upstream product remains .NET 10; see [product qualification](#complete-source-runtime-product)). |
| Ubuntu 26.04 ARM64 VMR source producer, 4 CPUs / 8 GiB | Built SDK 11.0.100 + runtime 11.0.0, built/ran net11.0 app; separate ARM64 guest ran probe on SDK-derived and standalone runtimes ([VMR qualification](#net-11-vmr-on-ubuntu-arm64)). |

Rosetta integration-test archive helper fails in GNU tar following Bazel symlinks (`Function not implemented`); direct quickstart passes without it (separate from `libarchive` extraction). Retained source-built SDK 10.0.100 and NativeAOT keep their own pins.

## Windows x64 qualification in progress

Native Windows Server 2025 x64 (10.0.26100), SDK **11.0.100**, runtime **11.0.0**, and MSBuild **18.12.2** passed direct GraphBuild and ProjectSync controls. A two-project offline fixture restored, generated its contract, built with **0 hits / 2 misses**, then recovered both project snapshots after deleting declared outputs (**2 hits / 0 misses**); the app ran. Native `tests/graph_build/{qualify,replay,configurations,design_time}.py` controls passed source/import invalidation, undeclared imports, overlapping outputs, multi-target compilation/replay, custom Restore layouts, and fresh design-time metadata. These are same-host, same-path tooling checks; native Bazel entry points, full acceptance, remote recovery, and Windows ARM64 remain unqualified.

The Windows image needed Git Bash and the Microsoft Visual C++ x64 Redistributable before native Bazel startup. Version **14.52.37029.0** resolved Bazel **9.3.2** exiting with `0xC0000135` (missing `MSVCP140.dll`, `VCRUNTIME140.dll`, and `VCRUNTIME140_1.dll`). Successful startup alone does not qualify the build entry points.

Windows contract paths use `/` while filesystem paths use native normalization. Native controls reject alternate data streams, device names, invalid filename characters, and trailing dots/spaces; ownership checks recognize case and separator aliases. These lexical checks do not detect Windows 8.3 short-name aliases or hardlinks. Unix filename behavior remains unchanged. Reproduce the portable source controls with `python3 tests/graph_build/input_integrity.py` and `python3 tests/graph_build/output_ownership.py` after building GraphBuild.

A separate AppContainer prototype passed declared-input reads, output writes, denied host reads/writes, denied SDK writes, and an inherited managed child token. Real SDK Restore/compilation and the two-project cold/warm graph action also passed inside it. This prototype is not a product filesystem boundary: SDK `Exec` tasks launching external programs through `cmd.exe` still fail, and cancellation, concurrent actions, cleanup, and general task compatibility remain open. Windows isolation is not enabled by these checks.

## Downloaded SDK platforms

Downloaded-SDK controls passed on native Linux ARM64 and Linux x64 **under Apple Rosetta**: 29 analysis/integration checks (8.8.0 / 9.3.0) + 21 SDK/runtime repo controls (SDK selection/locks, quickstart, Web/Razor Build/test/Publish + HTTP recovery, cached/uncached workers, body/API edits, raw parity; Web fixture verifies arch):

```sh
SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/analysis/... \
  //tests/integration:{quickstart,sdk_locks,sdk_policies,sdk_web,workers} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

Rosetta controls establish emulated x64 behavior only. Current native x64 coverage: [SDK 11 matrix](#sdk-11-platform-qualification), [source-runtime](#complete-source-runtime-product), and [source-SDK](#native-ubuntu-2604-x64-sdk) (automatic workers and whole upstream graphs remain unqualified).

Native macOS ARM64 passed `//tests/integration:{quickstart,native_sdk}` (8.8.0 / 9.3.0, SDK **10.0.400**: catalog packages, Razor/Publish, app/tests, body/API ref checks, sync/check, strict-lock consumer; ordinary sandboxed actions, remote off) and all 24 SDK/runtime repo controls (9.3; also passed on Linux ARM64; `native_sdk` ready for native x64 but unrun in SDK 11 matrix).

Visual Basic passed on Ubuntu 26.04 ARM64 with the full VMR SDK **11.0.100**, runtime **11.0.0**, and Bazel **9.3.2**. The fixture builds a C# app referencing a VB library, with explicit project roots and a conservative VB reference boundary. A VB method-body edit changed the app output from `VB:1` to `VB:2`. A fresh Bazel output base recovered the graph action from disk cache and ran the app again. A second edit produced `VB:3`. Reproduce on Linux ARM64 with `python3 tests/source_sdk/visual_basic_consumer.py /path/to/full-sdk.tar.gz NEW_DIRECTORY`. The downloaded SDK **10.0.400** previously passed `//tests/integration:visual_basic` on Linux ARM64 with Bazel 8.8.0 and 9.3.0. Automatic compiler-reference qualification and Compile globs remain C# only.

The full Linux ARM64 VMR SDK **11.0.100** builds an F# app and library with explicit, ordered `.fsi` and `.fs` inputs. Declare the SDK-bundled `FSharp.Core` in the package lock. The graph fingerprints implementation dependencies for F# and its consumers because inline bodies can change while the public signature stays the same. On Ubuntu 26.04 ARM64 / Bazel **9.3.2**, an inline edit changed the app result from 42 to 43. With a persistent local project cache and both projects’ bin/obj folders deleted between runs, an unchanged replay hit both projects. The inline edit missed both and returned 43. A separate fresh Bazel output base recovered the graph action from disk cache and reran the app. Reversing the signature and implementation produced compiler error FS0238. Reproduce with `python3 tests/source_sdk/fsharp_consumer.py /path/to/full-sdk.tar.gz NEW_DIRECTORY`. The compact C# toolchain omits the F# compiler.

## Qualified SDKs

Qualified on Linux ARM64 (Bazel 8.8.0 / 9.2.0): public sync, raw MSBuild parity, edits, failures, cached/uncached workers:

| SDK / project | Qualified behavior | Native suite (`//tests/integration:`) |
| --- | --- | --- |
| .NET | Managed graphs, Build/Publish, app/test layouts | `quickstart`, `workers` |
| Traversal 4.1.82 | Nested coordinators, conditional/wildcard references, multi-target children, Pack/Publish | `traversal` |
| NoTargets 3.7.0 | `.proj`/`.csproj` file producers, nested Traversal, explicit products and downstream invalidation | `notargets` |
| Worker + Hosting 10.0.11 | Worker template, Build/Publish and bounded execution | `worker_sdk` |
| IL 10.0.0-rtm.25509.106 | `.ilproj`, managed consumers, deterministic DLL/PDB, Build/Publish | `il_sdk` |
| Arcade 10.0.0-beta.25509.106 | SDK composition, versioning, Build/Pack/Publish and generated packages | `arcade_sdk` |

Web/Razor [graph controls](../tests/graph_build/web.py) cover compile/replay, Razor edits, and assembly attributes. `//tests/integration:sdk_web` passes cold on Ubuntu 26.04 ARM64 (SDK **11.0.100**, Bazel **9.3.2**, bundled ASP.NET without `runtime_host`; Build/test/Publish, compiled Razor + static assets; exact hashes + metadata except validated SDK `Last-Modified` timestamps; same cold check passes catalog with SDK **10.0.400**; 4-CPU / 6-GiB control, not general Blazor/Publish). Historical SDK **10.0.400** (8.8.0 / 9.3.0) also qualifies byte-exact HTTP action + forced project recovery (3 hits / 0 compilations, including timestamps).

C# design-time Compile passed on macOS ARM64 / SDK **11.0.100** with three linked projects, including incomplete C# source. The consumer resolved framework references and staged sources from the Bazel report, matched project references to their configured outputs, and observed edited symbols and source membership without compiling a DLL. After a Release build of GraphBuild, run `python3 tests/graph_build/design_time.py --bazel` with `RULES_MSBUILD_DOTNET_ROOT` set. IDE client integration, watch, and hot reload remain unqualified.

Blazor Server passed on native macOS ARM64 / SDK **11.0.100**. A Razor component rendered over HTTP, and an explicit SignalR `StartCircuit` invocation reached `CircuitHandler.OnCircuitOpenedAsync`. With outputs deleted, the graph plugin restored an identical app DLL (1 hit). A Razor edit rebuilt it (1 miss) and the new component rendered and opened a circuit. Run `python3 tests/graph_build/blazor.py` with `RULES_MSBUILD_DOTNET_ROOT` pointing to the pinned SDK after building ProjectSync and GraphBuild in Release. The fixture acquires the pinned static-assets package before offline Restore. Browser events, reconnect, WebAssembly, and Publish remain outside this control.

[Package-backed catalog](../examples/catalog-web/README.md) (5 projects: Newtonsoft.Json, Humanizer, embedded data, Razor, static assets): `SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test //tests/integration:catalog_web --test_output=errors` passed 8.8.0 / 9.3.0 on Linux ARM64 (Publish parity, body 4 hits / 1 compile keeping ref bytes, API 1 hit / 4 compiles, remote Restore/graph hits, forced 5-hit / 0-compile HTTP recovery; eval reuse off since Razor API changes can reevaluate).

`//tests/integration:sdk_locks` passed 8.8.0 / 9.3.0 on Linux ARM64 (metadata resolution, lock facts, platform expansion, metadata-free/cross-version recovery, extension reuse, stale/corrupt rejection, private archives; SDK **10.0.302** passed strict-lock without metadata; **10.0.400** retains quickstart). Historical `//tests/integration:sdk_versions` passed **8.0.425**, **9.0.318**, and **11.0.100-rc.1.26425.128** (predates stable-only adapter requirement; active matrix uses **10.0.302** and **11.0.100**; see [adapter requirements](api.md#sdks)). Historical `//tests/integration:sdk_policies` passed both pins on Linux ARM64 (patch/feature/prerelease selection, locked reuse, migration, refresh; `9.0.300` / `latestPatch` → **9.0.318**; `@dotnet//:update` + `--nuget-update`; active consumer requests `10.0.300` / `latestPatch` → **10.0.302**; all 24 repo controls passed on macOS ARM64 / 9.3; other roll-forward policies unsupported; uses published releases).

`//tests/integration:source_globs` passed both pins on macOS/Linux ARM64 (local/external-module compilation, body edits, pinned membership, undeclared cross-repo rejection). `//tests/integration:evaluation_worker` passed 8.8.0 / 9.3.0 on Linux ARM64 (reviewed body/API reuse, fresh state, eval-input/task changes, failure recovery; see [configuration](api.md#caching-and-workers) and [runtime timings](performance.md#reviewed-evaluation-reuse)).

## Project qualification cache

Configured-project keys use versioned structural records preserving ordinal property casing/values and separating embedded `;`, `=`, and `|`. Fingerprint epochs changed (old snapshots cold-miss). Qualification seed proofs are v2 (rerun sync to replace v1); retained Linux state v1 migrates cold (clears validated outputs, rewrites v2; other mismatches fail). Graph contract schemas are unchanged.

Closed sync enables HTTP project reuse automatically when complete `srcs`, package/ref qualification, qualified Linux execution, and a project HTTP endpoint are available (`qualification_cache = True` forces Linux; `False` disables; see [default eligibility](api.md#sync)). Linux ARM64 / SDK **10.0.400** passed small controls on both Bazel pins (declaration parity, forced empty-cache prep, body/API invalidation, independent-branch reuse, app execution, Newtonsoft.Json **13.0.3** materialization/recovery; ProjectSync controls cover props/mode changes, multi-target, impl/ref DLLs, XML copies, failures, corruption, relocation, aliases, overlapping owners).

Environment fingerprinting reuses content digests for file links to the same target inside the immutable SDK within one pass (logical names, order, and modes stay keyed; later passes reread; external targets bypass reuse; dir aliases/hard links may miss). Ubuntu 26.04 ARM64 warm-cache complete-env medians (4 alternating legacy/production pairs; fingerprint timings only):

| SDK layout | Legacy median | Production median |
| --- | ---: | ---: |
| Downloaded SDK 11.0.100 | 0.326 s | 0.253 s |
| Retained source SDK 10.0.100 (`e043c131`) | 0.704 s | 0.554 s |

Run `python3 tests/graph_build/qualification_environment.py --full` on Linux (`RULES_MSBUILD_DOTNET_ROOT` + `/usr/bin/bwrap`; omit `--full` on macOS).

Conditional-default fixture passed on Linux ARM64 / SDK **10.0.400** (both pins: package-free closed sync, fallback, disable/force, auto qualification/seeding, portable consumers; 3-project Build recovered all seeded snapshots, body/API kept **2 / 1** hits matching uncached bytes; inferred Restore keys source contents without making them shared Build inputs):

```sh
QUALIFICATION_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/integration:defaults --test_output=errors
```

Complete source-runtime graph passed on 9.3: all 563 projects replayed over HTTP; Pipelines body/API ran 11/26 Csc tasks with identical declarations. With `--cache-url`, source-runtime setup enables reviewed Restore reuse for `PipeOptions.cs` + ref source (launcher caps remote connections at 8, 60 s timeout; `--bazel-cache-read-only` disables Bazel uploads; `RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1` disables project uploads; names/modes/defs/packages/other contents stay keyed; see [timings](performance.md#source-runtime-product)).

Verified Restore snapshots passed small controls (compiler-only edits, membership/modes, failures, corruption, Restore-hook inputs, empty generated dirs, synthetic package-SDK resolution; serial/parallel multi-target keeps SDK selections; root `restoreReuseInputs` requires review; stopped-producer relocated VM recovered Restore + 4 projects over HTTP with 0 compilations). Both qualification and consumer sandboxes disable CLI/MSBuild servers (must match for seed reuse).

Build snapshot seeding (`seed_build_cache = True` or auto with qualified execution) passed 3-project, 5-node/2-framework, query-only coordinator, glob, and generated-file controls on Linux ARM64 (SDK **10.0.400**, 8.8.0 / 9.3.0): first Builds recovered all snapshots (0 compilations), fresh consumer recovered over HTTP with Bazel caching off (matching uncached bytes except `AssemblyReference.cache`), body/API missed 1/2 projects, config/failure/Restore-mutating targets rejected reuse, and Traversal **4.1.82** / NoTargets **3.7.0** controls passed. On 9.3, the complete managed runtime graph (631 configs) recovered all 563 seeded snapshots with matching keys/manifests and 0 Csc/Vbc calls or build-node evaluations.

On Ubuntu 26.04 ARM64 with SDK **10.0.400** and Bazel **9.3.2**, the [Pack/Publish handoff fixture](../tests/integration/qualification_seed_targets.sh) consumed three Build snapshots from qualification with Bazel action caching disabled. Both targets ran their own hooks and made **zero** compiler calls. Each cold control compiled all three projects. The packaged DLL, PDB, and nuspec contents and the published files matched between runs. Editing a dependency method body recompiled one project, and editing its public API recompiled two. The published app returned the edited value. A separate macOS ARM64 SDK **11.0.100** control matched cold and seeded package contents and publish files, ran the published app, and rejected a changed output path. Run `QUALIFICATION_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test //tests/integration:qualification_seed_targets --test_output=errors`. See [consumer configuration](api.md#compiler-selections).

Requires qualified Linux/bwrap with user namespaces and writable `/proc` (as in `scripts/run-apple-container.sh`; stable-path isolation only—declare custom inputs/tools; non-assembly projects run normally; overlapping owners skip reuse; see [configuration](api.md#compiler-selections) and [measurements](performance.md#project-qualification-reuse)):

```sh
QUALIFICATION_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test \
  //tests/integration:{qualification_cache,qualification_seed} --test_output=errors
```

Legacy acceptance still rejects synthetic `Fixture.Sdk` and stops at archive/lock hash mismatches; use the native command above.

## Downloaded SDK and runtime sources

Public `dotnet.sdk(version="10.0.400")` → NuGet update/check → offline sync/check passed on runtime v10.0.0 (Linux ARM64, Bazel 9.3.0; retains out-of-process `Runtime="NET"` tasks):

| Slice | Configurations / compilations | Archives / native locks | Compiled files matched |
| --- | ---: | ---: | ---: |
| Four managed roots | 182 / 163 | 106 / 91 | 1,447 |
| 39 roots / eight suites | 543 / 481 | 141 / 265 | 3,622 |

Both passed paired body/API parity, compiler-workset controls, and stopped-producer recovery (normal Restore + graph hits, then forced HTTP hits with 0 compilations and identical bytes/modes). Large slice consumer runs app + 8 suites after normal hits and after forced **481 HTTP hits / 0 compilations**, matching **10,780 files/modes**, **118,952 passed / 64 skipped** cases, and source-runtime hashes (test caching off; see [measurements](performance.md#large-downloaded-sdk-graph) and [CI demo](performance.md#runtime-ci-demo)). Clean setup, interrupted resume, and post-deletion recovery pass on Linux ARM64. Batched layouts (`msbuild_graph_layouts`) passed 8.8.0 / 9.3.0 (1 action replacing 124 host exports, matching 490 files/modes; stopped-producer recovered **186 build actions + 9 test results**, body/API ran all 9 tests with **6 / 17** compilations). Bounded slice only (not full runtime repo, full source SDK, Linux x64, or RBE).

## NuGet inventories

All suites below passed on Linux ARM64 (Bazel **8.8.0 / 9.3.0**, SDK **10.0.400**, NuGet.org V3, standard lockfiles; see [API](api.md#nuget-updates)):

- `solutions` / `solutions_remote`: `.sln`/`.slnx` update, strict locks, offline sync/test, DLL parity, mappings/exclusions/deps, stale rejection, 4-project 0-compile recovery (single solutions without custom hooks).
- `nuget_update`: explicit update/check, offline locks, app/Razor/Publish, corrupt/malformed rejection, lock preservation on failure (also passed macOS ARM64 / 9.3).
- `PrivateAssets` through Pack: with SDK **11.0.100** on macOS ARM64 and the full Ubuntu 26.04 ARM64 VMR SDK, graph Pack matched the raw SDK nuspec dependency metadata. An empty-cache offline consumer restored only the exported library, its public dependency, and its runtime-only dependency (`PrivateAssets="compile"`). It called the public API, loaded the runtime-only assembly, and failed compilation against either restricted API. `PrivateAssets="all"` omitted the dependency entirely. Pack replay restored the identical archive. Run `python3 tests/graph_build/private_assets.py` with the Release GraphBuild runner and `RULES_MSBUILD_DOTNET_ROOT` set to the SDK.
- `nuget_graph`: central versions, transitive Options, multi-TFM Newtonsoft, packaged CA1822 (config-only toggle without sync), strict-lock offline consumer, `ProjectInstance` inner-TFM skipping, workspace-bounded SDK discovery (31 sync controls), HTTP graph recovery (catalog also passed macOS + 9.3→8.8 contract check).
- `nuget_hierarchy`: config inheritance/clears, disabled sources, nested mappings, attestation, outside-config rejection, Traversal/NoTargets HTTP recovery (also passed macOS ARM64 / 9.3).
- `nuget_configured` & `nuget_shared_projects`: shared/entry properties, all-TFM locks, escaped values, shared-dir project locks, drift/collision rejection.
- `nuget_sdks`: Traversal **4.1.82** / NoTargets **3.7.0 → 3.7.56**, global/inline selection, invalidation, offline HTTP recovery.
- `il_sdk`, `arcade_sdk`, `*_remote`: generated inventories, Build/Publish (and Arcade Pack) parity, edits, failure recovery, 2-project 0-compile HTTP recovery; IL **10.0.0-rtm.25509.106** (ILAsm/ILDasm), Arcade **10.0.0-beta.25509.106**.

Reproduce: `SDK_WEB_CACHE_URL=http://cache:8080 bash scripts/bazel.sh test //tests/integration:{nuget_update,nuget_graph,nuget_sdks,native_sdk,catalog_web,sdk_policies} --test_output=errors`.

## Downloaded runtimes

Active fixtures compile net10.0 with SDK 10.0.302: runtime locks test 9.0.20 (older-major reject), 10.0.12 (match), and 11.0.0 (default reject / `RollForward=Major` pass); ASP.NET tests CoreCLR/ASP.NET 10.0.12 and ASP.NET 11.0.0 (require fresh qualification).

Historical SDK **9.0.318** (Linux ARM64, 8.8.0 / 9.3.0; 25 analysis/integration checks + 17 repo controls) qualified net9.0 CoreCLR (**9.0.20** match, **8.0.31 / 10.0.12** default reject, **10.0.12** `RollForward=Major`) and ASP.NET (CoreCLR-only/cross-major reject, composite/targeting-pack exclusion, whole-action + forced 3-hit / 0-compile HTTP recovery, metadata-free blocked-URL acquisition on 9.3):

```sh
RUNTIME_CACHE_URL=http://cache:8080 \
  bash scripts/bazel.sh test //tests/analysis/... \
  //tests/integration:{aspnet_runtimes,runtime_locks,sdk_locks,quickstart} \
  --test_output=errors
python3 -m unittest discover -s tests/sdk_repository -v
```

Small managed fixtures on one host; other shared frameworks need a complete declared layout (see [runtime configuration](api.md#runtimes)).

## Graph executable and test launchers

Bazel **9.3.2** / SDK **11.0.100** on Ubuntu 26.04 ARM64: both executable staging modes passed (default writable test returned exit 7; runfiles included declared runtime/app and omitted compiler runtime + `ArtifactTools.dll`; `python3 tests/graph_build/direct_executable_smoke.py`). On macOS ARM64, `python3 tests/graph_build/executable_launcher.py` verified stdin/pipe, descendant cancellation, collisions, and output dirs; a Bazel binary returned 100 via dotnet/runtime v11.0.0 CoreRun (`expected_exit_code = 100`).

On Linux ARM64, `python3 tests/graph_build/protocols.py` (ordinary + `--graph-worker` + mixed-runtime .NET 11.0.0 adapter / .NET 10.0.10 test CoreLib) passed MTP and VSTest pass, failure, filtered, empty-selection, and dep-edit cases. On macOS, the protocol adapter built/tested on SDKs 10.0.400 and 11.0.100, and a .NET 11 adapter launched a .NET 10 app on 10.0.11.

## Graph inputs

- `//tests/integration:preparation` (Linux ARM64, 8.8.0 / 9.3.0): shared multi-root offline Restore, root hooks, escaped/per-root props, all-TFM Restore, parallel private Build (≤4 nodes, CPU-bounded; see [measurements](performance.md#parallel-compiler-qualification)).
- `//tests/integration:cached_sync` (Linux ARM64, SDK 10.0.400, 8.8.0 / 9.3.0): declared-source prep, cached checks, invalidation, shell tasks, directory producers (rejecting authored links), and stopped-producer strict-lock recovery (4-project, runtime-bootstrap, 543-config managed, and live runtime/JIT handoff with **227 remote hits / 0 executions**, 5 native producers, 6 JIT tests, forced 9-hit / 0-compile JIT recovery via `runtime_jit_public_consumer.py --preparation-base=BASE`; see [cached preparation](performance.md#cached-preparation); RBE unqualified).
- `//tests/integration:source_globs`, `:dynamic_sources`, `:recursive_sources` (Linux ARM64, 8.8.0 / 9.2.0): body edits, add/remove/rename/empty sets without sync/Restore (recursive covers new subdirs and `bazel-*` filenames), 3-eval reuse on body edits, membership reset, guard rejections, and HTTP recovery (`DYNAMIC_SOURCE_CACHE_URL`; small fixture on one host).

<a id="traversal-projects"></a>

Traversal coordinators keep Restore state without emitting assemblies (reject dynamic skipping, per-ref target overrides, `TraversalPublishGlobalProperties`; use conditional refs + explicit props). NoTargets requires reviewed tasks and `outputFiles` (Build only). IL requires locked ILAsm/ILDasm (`IlasmFlags=-DET`; hashes impl without ref assembly). Arcade requires implicit packages, explicit version/repo inputs, `OfficialBuildId` for shipping, `GeneratePackageOnBuild=false` for cold Pack (ambient Git/Helix/full native Arcade unqualified).

## Source toolchains and NativeAOT

### .NET 11 VMR on Ubuntu ARM64

[ARM64 VMR recipe](../tests/source_sdk/LINUX_ARM64_11.md) builds SDK **11.0.100** and Core/ASP.NET **11.0.0** (`ubuntu.26.04-arm64`) from signed release VMR commit `297acf930fb0f5c07fd4e51d78e521b4ad2e5d1f` using Clang 18.1.8 and [pin](../tests/source_sdk/pin-linux-arm64-11.json):
- Standalone Core runtime archive: **75,756,582 bytes**, SHA-256 `2600fd21410a9f04aa10b8130195b8e95dd87369efb1712578940edbb36c68d0` (ARM64 ELF host, hostfxr, CoreCLR, JIT).
- SDK archive: **411,487,487 bytes**, SHA-256 `993765849ca1f97d64ca1a157b34158b37dc75facff43d41707365dc8724ec85` (native binaries match standalone runtime byte-for-byte).

Producer Bazel smoke test built/ran a net11.0 app on 11.0.0; a separate ARM64 guest on the Mac mini ran the app DLL on both the SDK-derived and standalone Core runtimes. With producer stopped, a fresh guest recovered all 12 Bazel actions from read-only HTTP cache in **957 s** (matching SDK digest), ran body/API edits without rebuilding SDK, and passed NuGet Pack/consume, Razor, and Publish/run (runtime 11.0.0).

The pinned VMR11 C# layout omits `sdk/11.0.100/DotnetTools` and `FSharp` (214.55 MiB combined), plus the two NativeAOT packs. Extraction checks the seven pack directories and the immediate SDK version-directory inventory. The full compiler retains their original paths (`--extra_toolchains=//:produced_registered`). On Ubuntu 26.04 ARM64, the compact layout passed a Bazel graph build and forced smoke, NuGet Pack/consume, Razor rendering, and framework-dependent Publish/run. Earlier qualification exercised offline NativeAOT Publish/run with the full toolchain and Clang 18.

Direct launcher passed Linux x64 downloaded-SDK control (`python3 tests/graph_build/direct_executable_smoke.py`, Bazel 9.3.2, runtime 11.0.0: CoreLib path, args, nonzero exit, missing-host; [historical ARM64 measurements](performance.md#retained-archive-launcher-and-connection-control)).

The [full SDK zstd handoff](../tests/source_sdk/LINUX_ARM64_11.md#smaller-transfers) uses Python 3.14 and libzstd 1.5.7 at level 9 with long-distance matching and a 64 MiB window. The retained 411,487,487-byte SDK compressed to **323,545,085 bytes** (21.4% smaller). Both formats decoded to the same tar SHA-256. A separate Bazel workspace verified the compressed digest, extracted a suffixless archive with `type = "tar.zst"`, compiled a graph app with the acquired SDK and ran it on 11.0.0. Gzip remains available as `//:sdk`.

### .NET 10 VMR on Ubuntu ARM64

Coarse producer rebuilt pinned .NET 10 VMR on Ubuntu 26.04 ARM64 / Clang 18.1.8 / Bazel **9.3.2** → SDK **10.0.100** + Core/ASP.NET **10.0.0** (controller SDK 10.0.400; upstream bootstrap SDK/artifacts declared; [native overlay](../tests/source_sdk/native_overlay/README.md) records Ubuntu 26 / LLVM 18 packages and sealed root hash). Stopped-producer fresh read-only consumer recovered `SourceSdkBuild`, layouts, and graph over HTTP (matching hash, **0 PUTs**, unchanged cache bytes), then ran body/API edits and forced smoke without rebuilding SDK. Cold consumer against SDK 11 migration candidate passed Pack, Razor, Publish/run, and identity checks using only this archive (no StaticWebAssets supplement; see [method/pins](performance.md#source-sdk-production-and-recovery)).

[Producer](../tests/source_sdk/source_action_prepare.py), [recovery driver](../tests/source_sdk/source_action_recovery.py), and [consumer controls](../tests/source_sdk/consumer_scenarios.py) require declared bootstrap inputs. Successful `result.tar` defaults to last 65,536 bytes each of prep/build logs + timing/SDK info (`--full-diagnostics` retains full logs and `artifacts/log`, changing action identity; failure logs always appear in action output). See [quick start](../examples/quickstart/README.md#source-built-sdk). Older-glibc deployment, signing, and full upstream parity remain unqualified.

### Native Ubuntu 26.04 x64 SDK

Coarse producer passes on native Ubuntu **26.04 x64**, Clang **18.1.8**, Bazel **9.3.2** ([rules `de47cfe1`](https://github.com/keegan-caruso/msbuild-bazel/commit/de47cfe1df06e6ec82d14aff56425af6e6227b93)): VMR `b0f34d51fccc69fd334253924abd8d6853fad7aa` → SDK **10.0.100** + Core/ASP.NET **10.0.0** (`ubuntu.26.04-x64`; [recipe](../tests/source_sdk/LINUX_X64.md), [pins](../tests/source_sdk/pin-linux-x64.json), controller SDK 10.0.400, unchanged VMR bootstrap project + [IdentityModel patch](../tests/source_sdk/patches/identitymodel-file-version.patch)). Fresh output base runs **1 uncached `SourceSdkBuild`**, then smoke, generated-package (`42`), Razor HTML, and Publish/run (`SOURCE_SDK_PUBLISH`) with no further source build:

| Native product | Archive bytes | SHA256 |
| --- | ---: | --- |
| Smoke-first direct producer and consumers | 578475269 | `1ead53dd86c9cf61fdeff9836e618b2fddb555ac0df5547f8f89203a71caff4c` |
| Earlier source producer, verified by a separate exact-archive consumer handoff | 578486969 | `e4415b51444d2c85652f6e061f31c001cdd77e9f60e2bc9548167c8f50abb924` |

Earlier product (`b26d759cc0abde7e9e0365742e2eb943db958d37`) also passed all consumer checks with archive declared as input (0 source actions; separate observations, no byte-reproducibility/speedup claim). Prerequisites: host GCC/G++, pinned bootstrap tools, Python/`dpkg-deb`, case-sensitive FS, nested namespaces, catalogued native closure; `--system-bwrap` requires root-owned packaged Bubblewrap **0.11.1-1ubuntu0.3** generic amd64 (`523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6`; `amd64v3` bytes differ). SDK root declares UID/GID 0 and **1000** (home `/tmp`; unresolved caller IDs rejected; `test_sdk_accounts.py` passes; arbitrary UIDs unqualified). Component scheduling, older-glibc, RBE, signing, and upstream test parity remain unqualified for x64.

On [rules `a0774a86`](https://github.com/keegan-caruso/msbuild-bazel/commit/a0774a863749e41b1d3d3605d5fd4723123846b6), a native x64 SDK producer seeded an empty HTTP cache and stopped. A fresh input-only consumer on the **same host** recovered all 10 actions, including `SourceSdkBuild`, with zero executions and zero attempted PUTs. The recovered 578,504,698-byte SDK archive matched the producer (SHA256 `322aefcd7cfcbd4e76625ed86d1c3ae9937559b90f7a9c788e92040228af23db`). A separate forced smoke test executed and printed `SDK_FROM_SOURCE=10.0.0`. In this single run the cold seed took 3,423 s, recovery took 522 s, and the forced smoke test took 11 s.

The [NativeAOT Publish fixture](../tests/source_sdk/native_aot_x64/README.md) uses the retained source-built SDK **10.0.100** (SHA-256 `322aefcd7cfcbd4e76625ed86d1c3ae9937559b90f7a9c788e92040228af23db`) and its bundled ILCompiler, ILLink, and NativeAOT packs for `ubuntu.26.04-x64`. On native Ubuntu 26.04 x64, graph Publish used declared Clang and LLD **18.1.8** (native archive SHA-256 `84373f449ce597c6b467db1fd77ca9deb04d20b28440fedaf938800ee486410b`). The exported package yielded a standalone x86-64 ELF that reported dynamic code disabled when run from an empty directory with no .NET runtime supplied.

### Historical consumers and NativeAOT

Earlier Bazel 9.2 component consumers used Ubuntu 22.04 + StaticWebAssets supplement ([producer](../tests/source_sdk/component_graph_prepare.py), [pins](../tests/source_sdk/pin.json)); separate Bazel 9.3.2 retained-archive control passed ([results](performance.md#retained-source-sdk-consumer-recovery)).

Graph NativeAOT Build/Publish/run, body edits, missing-compiler rejection, and independent 1-hit / 0-compile ELF-exact recovery passed historically on Linux ARM64 with the retired LLVM 14 catalog (downloaded AOT packs + declared tools only; not source-built AOT or RBE). Active SDK consumer driver: [SDK consumers](../tests/source_sdk/consumer_scenarios.py).

## Runtime and cache evidence

Runtime and source-SDK native qualification share `tests/runtime/NativeBuild.cs.txt` (`--sdk-archive` / `--sdk-layout` for SDK components). Ubuntu 26.04 ARM64 / SDK **11.0.100** passed 26 Bubblewrap differential controls (byte-identical archives/layouts/modes, staging, overrides, errors, cleanup; declared and packaged launchers). Explicit `--system-bwrap` verifies root ownership via Linux `statx` (non-symlinks `/`, `/usr`, `/usr/bin`, launcher; not group/other writable; executable + SHA-256 match; `NativeBuild.SelectSandbox` probe passed on Ubuntu 26.04 ARM64 / SDK **10.0.400** even with `/usr/bin/stat` symlinked to Rust coreutils).

Managed runtime fixture (**260 paths / 543 configs / 481 compilations / 39 roots**, Linux ARM64, Bazel 9.2.0) passed **118,952 tests, 64 skips, 0 failures**. Complete compiler inventories compile **1 / 47** projects on LINQ body/API edits (matching **2,814 required files**); generic sync captures all **2,970** compiler selections. `resolved_inputs`, `resolved_package_copies`, `resolved_il_sdk` (8.8.0 / 9.2.0; plus `resolved_inputs` and `restore_inputs` on 8.8 / 9.3) pass static role snapshotting, direct-edge analyzer assignment, build-only producer edits without Restore, and 20 sync rejection controls. Normal remote recovery hits Restore + graph; forced stopped-producer recovery yields **481 hits / 0 compilations** matching **9,972 files/modes** (Traversal, NoTargets, Worker, IL, Arcade also passed Bazel-cache-off HTTP recovery; see [performance](performance.md)).

### Unchanged JIT tests

Six runtime v10.0.0 tests pass on source-built corerun (Linux ARM64, 4 CPUs / 6 GiB, SDK **10.0.400**, Bazel **8.8.0 / 9.3.0**):

| Project | Behavior |
| --- | --- |
| `CodeGenBringUpTests/Add1_ro` | Arithmetic |
| `CodeGenBringUpTests/Switch_ro` | Control flow |
| `CodeGenBringUpTests/FactorialRec_ro` | Recursion |
| `CodeGenBringUpTests/ArrayExc_ro` | Exception handling |
| `Generics/ConstrainedCall/vt1_cs_ro` | Constrained generic calls |
| `Directed/PREFIX/PrimitiveVT/callconv1_PREFIX_cs_ro` | Cross-assembly value-type calls through `helper.csproj` |

All **36 DLL/PDBs** and **69 deployed files** match raw bytes; raw binaries run SDK-absent. Edits: body **8 hits / 1 compile**, generator **2 / 7**, helper body/API **7 / 2** (`--compiler-references` binds `helper/helper.dll`), codes **100 / 101** preserved, 36 sync controls pass. Stopped-producer consumer (27 MB source bundle, action/disk/test caches off) recovered **9 HTTP snapshots / 0 compilations** and ran all 6 tests (deployment project reruns without emitting an assembly). Reproduce (set `RULES_MSBUILD_PROJECT_CACHE_URL`; fixture maps `Microsoft.Diagnostics.NETCore.Client` to `dotnet-public`; inspect boundary with `runtime_jit_reference_probe.py RAW_RESULTS SDK_ROOT REPORT.json`):

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

Independent recovery: `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json FRESH`, relocate, stop producer, rerun qualifier with `--seed-report=FRESH/seed.json` and fresh `--output-base`.

Runtime demo checkpoints preserve ordinary permissions and internal hardlinks while stripping special bits (`test_runtime_demo_setup.py` passes all 11 controls on Ubuntu 26.04 / Python 3.14.4 under umasks `022`, `002`, `077`).

### Complete source-runtime product

Newer bootstrap SDKs select net10 targeting pack versions from bundled SDK props; the app graph declares only those packages from the verified NuGet lock and records their archive hashes (portable controls cover selection, SDK 10 no-package path, and mismatch rejection).

[Source-to-app workflow](../examples/source-runtime-app/README.md) builds an unsigned IL developer runtime (**172 managed assemblies** + **16 native files**: globalization, network security, standalone GCs, debugging libs, `createdump`; keeps upstream licenses and provenance; no signing/ReadyToRun/release-pack parity). On Apple silicon, `--worker-memory-gib` sets worker memory (default 8 GiB; use **12 GiB** for SDK 11 since 8 GiB OOMed; 2-CPU / 512-MiB probe verified mounted socket, relay restart, and TLS HTTPS status):

```sh
python3 scripts/setup-source-runtime.py OUTPUT --worker-memory-gib 12
bash OUTPUT/run.sh --describe-runtime --verify-product
```

Source prep applies one reviewed linker adaptation before discovery (`StringBuilder.Append(new string(character, count))` → `Append(character, count)` for SDK 11 CA1830; original hash checked before adaptation, resume verifies transformed bytes). Current producers require Ubuntu 26.04 ARM64 or x64 with LLVM/Clang **18.1.8** and glibc 2.43 (older-glibc deployment and RBE unqualified; the former Ubuntu 22.04 manual CI workflow and LLVM 14 NativeAOT catalog have been removed). Declared-environment probe (`python3 tests/runtime/environment_probe.py FRESH_OUTPUT --source-archive PINNED_SOURCE`) passed in a 6 GiB ARM64 guest (194 packages, Ubuntu 26.04, Clang 18.1.8, GNU coreutils 9.7).

Qualification runs (all verify 172 framework members, bytes/modes, archive contents, SDK-absent execution, and missing-CoreCLR rejection):
- **Native Ubuntu 26.04 x64** (rules `7e82ad6fe3d19e22be67c569a2c493ed1a785585`, runtime **10.0.0** `60629d14374c56f1cb51819049ad1fa529307f8d`, SDK **11.0.100**, Bazel **9.3.2**, Clang **18.1.8**, 6-CPU / 22-GiB controller, .NET 4 CPUs, `-numproc 4`, `--jobs=1`): built 3 native producers + **631 configs / 563 compilations** (121 archives / 320 locks); resumed after deadline to pass 2/2 forced tests; `runtime-linux-x64.tar.gz` SHA-256 `08199700d6f2e5c2bf32c7d3b32ef2294f26adcd4504f8ecb10d828ce92e28f6` (same-host only; `--system-bwrap` requires exact generic `amd64` `0.11.1-1ubuntu0.3`, not `amd64v3`; host GCC/G++ needed for `rules_pkg`/`rules_cc`; see [guide](../examples/source-runtime-app/README.md#native-linux-x64) and [x64 SDK](#native-ubuntu-2604-x64-sdk)).
  - **Stopped-producer HTTP recovery on the same native host.** An input-only consumer recovered 140 build actions, including all three native producers and all three managed graphs. Bazel locally unpacked the declared native toolchain (`//native:tools` uses `no-remote`); its 14,996 entries matched the producer. All 649 runtime files and their modes matched, as did the archive SHA above. Recovery took 70.90 s and downloaded 5,347,668,317 HTTP response-body bytes. Both forced tests then ran in 21.70 s and downloaded another 29,001 bytes. The build had zero HTTP misses. Generating the forced test’s XML output had one cache miss. The consumer attempted zero PUTs throughout. These are single observations.
  - Reproduce with the [native HTTP recovery driver](../tests/graph_build/upstream/runtime_http_recovery.py) against the pinned [prepared x64 workspace](../examples/source-runtime-app/README.md#native-linux-x64). Its `--system-bwrap` test requires the exact generic amd64 binary (SHA256 `523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6`). The cold build produced the runtime, but its runtime test rejected a different installed binary. The passing consumer ran with the pinned binary mounted at `/usr/bin/bwrap` in a private mount namespace.

    ```sh
    python3 tests/graph_build/upstream/runtime_http_recovery.py "$SETUP/workspace" "$FRESH" \
      --rules "$PINNED_RULES" --expected-revision 7e82ad6fe3d19e22be67c569a2c493ed1a785585 \
      --bazel "$BAZELISK" --repository-cache "$REPO_CACHE" --distdir "$SETUP/downloads/nuget-dist"
    ```

- **Ubuntu 26.04 ARM64 SDK 11** (4 CPUs / **12 GiB**, Bazel **9.3.2**, Apple Container **1.7.1** / init **0.54.0**): compiled graph, assembled 649-file archive SHA-256 `aaecfc189f42d0793acc273199ad50d46aa873b765ad4d21741291df27bf3f3f`, passed both forced tests + retained host launcher (0 OOM). With producer stopped, a fresh consumer on a second Mac (Container 1.7.1 / init 0.54.0) passed read-only recovery (all 3 graph actions, Restore, 3 native producers, version gen hit with misses prohibited; both tests ran; 649 files + archive matched; **27,622 GETs / 0 PUTs**).
- **Ubuntu 26.04 ARM64 SDK 10** (4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.2**, Clang **18.1.8**): 563 misses / 0 project hits; resumed after host interruption reusing cached native outputs; 22 MiB archive SHA-256 `5bc7ec87952a0062eaaf991e7a04fd8b090e4f73c95139d7ea96db2a71d0d3a6` ([phases](performance.md#source-runtime-product)).
- **Historical Ubuntu 22.04 ARM64** (4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.0**): 631 configs / 563 compilations, 119 archives, 320 locks; stopped-producer consumer recovered all **649 runtime files** + archive (package extraction sole local action) and source-only consumer recovered `MSBuildSyncPrepare` (122 remote hits / 0 executions; [timings](performance.md#source-runtime-product)). For compiling with a source-built **SDK**, see [quick start](../examples/quickstart/README.md#source-built-sdk).

### Declared native preparation

Source selection, 3 version files, shared source archives, and tool trees are Bazel outputs. ARM64 uses 194 hash-locked Ubuntu 26.04 packages; x64 uses [native-packages-x64.json](../tests/runtime/native-packages-x64.json) (incl. compiler-rt) and [native-packages-sdk-x64.json](../tests/runtime/native-packages-sdk-x64.json) referencing [shared x64 records](../tests/runtime/native-packages-shared-x64.json) by name + canonical JSON SHA-256 (assembler writes expanded catalog for provenance). Clang/LLD/LLVM pinned to `1:18.1.8-20ubuntu8`; explicit aliases replace package scripts (`Etc/UTC` for `/etc/localtime`); extraction uses host `dpkg-deb`, compilation uses declared tool FS.

Historical `//tests/integration:native_preparation` (8.8 / 9.3, Ubuntu 22.04) verified suffixless URLs, body/version invalidation, Brotli nested BUILD, failure recovery, link-preserving archives (**7,806 members** matched), and downloader-off / experimental HTTP repo-contents recovery (producers: `//native:{runtime_coreclr,runtime_libraries,runtime_host}`).

### Connected source-runtime workflow

Set `RULES_MSBUILD_PROJECT_CACHE_URL` and prepare (qualified Linux ARM64 container, nested namespaces, Python, download access, 12 GiB headroom; `--resume` validates inputs; pins `Microsoft.TestPlatform.ObjectModel` to `dotnet-public`):

```sh
python3 tests/graph_build/upstream/runtime_checkout_prepare.py SOURCE_ARCHIVE PREPARATION \
  --toolchain=NATIVE_TOOLCHAIN_TAR --toolchain-sha256=TOOLCHAIN_SHA256 \
  --sandbox=BWRAP --sandbox-sha256=BWRAP_SHA256 --host-space-path=HOST_BIND
```

Runs public NuGet update/check + sync/check for **543 configs / 481 compilations**, generates 5 native producers (byte-exact archives), and syncs the 6-test JIT graph (`@jit_source_runtime//:references` and `:host`; `bazel test //:jit_tests` needs no intermediate `source-products.tar.gz`; existing producer can connect via `runtime_jit_public_prepare.py --source-producer=WORKSPACE --cases=tests/graph_build/upstream/runtime_jit_cases.json --compiler-references --host-space-path=HOST_BIND`).

Stopped-producer Bazel 9.3 consumer remotely recovered Restore, managed graphs, and 5 native actions and ran all 6 tests; forcing JIT graph recovered **9 HTTP snapshots / 0 compilations** and reran tests. Reproduce: `runtime_jit_live.py OUTPUT RESULTS --output-base=OUTPUT/bazel --bounded-seed=BOUNDED_RESULTS/seed.json --host-space-path=HOST_BIND`, close with `runtime_jit_public_consumer.py OUTPUT RESULTS/seed.json FRESH`, relocate and stop producer, then run `runtime_jit_live.py FRESH RESULTS --output-base=FRESH_BASE --seed-report=FRESH/seed.json --host-space-path=HOST_BIND`. Connected edits rerun all 6 tests (`build_inputs` on 138 ref files keeps JIT Restore across API edits; **2,908 Restore files** match):

| Edit | Runtime compilations | JIT compilations | Native actions | Restore actions |
| --- | ---: | ---: | ---: | ---: |
| Pipelines body | 6 | 0 | 0 | 0 |
| Pipelines API | 17 | 9 | 0 | 0 |
| Native version marker | 0 | 0 | 1 | 0 |

Body preserves ref/JIT bytes; native changes only `libSystem.Native.so`; restoring recovers original bytes/modes (0 executions); fresh machine recovered API-edited closure with producer stopped (0 build/Restore executions, 6 test runs; correctness controls, not paired timings):

```sh
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py OUTPUT RESULTS \
  --output-base=OUTPUT/bazel --host-space-path=HOST_BIND \
  --case=api --close-api=EDITED_INPUTS
# Relocate EDITED_INPUTS, stop the producer; use a fresh output base:
python3 tests/graph_build/upstream/runtime_jit_connected_edits.py EDITED_INPUTS RECOVERY \
  --output-base=FRESH_BASE --host-space-path=HOST_BIND --recover=EDITED_INPUTS/seed.json
```

Omit `--case` for body + API + native. Bounded graph only (no full repo bootstrap, signing, native toolchain bootstrap, other archs, or RBE). `worker_preparation.py` (and `--cache-mb=0`) plus `//tests/integration:{workers,evaluation_worker}` (6 controls on 8.8.0 / 9.3.0) passed concurrent staging, mode preservation, corruption/overlap rejection, and failure recovery.

## Project-cache publication

Use serialized publishers per endpoint/namespace and explicit read-only consumers (HTTP AC lacks compare-and-swap for divergent writers; default is read-write; see [cache configuration](api.md#caching-and-workers)).

Native macOS ARM64 / SDK **10.0.400** passes `remote_publication.py` and `remote.py` (identical writers, concurrent readers, divergence rejection, no-PUT consumers, 3-project HTTP recovery, eviction, interrupted downloads, corruption). The native macOS synthetic snapshot check (stopped MacBook publisher → read-only Mac mini consumer) matched SHA-256 over HTTPS. For Linux guests, see the [two-host quickstart](#cross-host-downloaded-sdk-graph-recovery) and [native x64 controls](#native-linux-x64-controls).

## Linux worker qualification

Ubuntu 26.04 ARM64, SDK **10.0.400**, Bazel **9.3.2** (4 CPUs / 6 GiB, 2 jobs, 1 local test, 1 worker) passes cached/zero-budget workers and retained evaluation: forced worker tests **2/2** (**105.1 / 104.4 s**), retained evaluation **75.8 s**, private worker HOME/working-dir proof. Real process/broker controls pass bounded noisy output, deadlines, live cancellation, descendant cleanup, isolation, retries, idle-crash lease reclamation, and cleanup (controlled child replaces MSBuild; Bazel-initiated cancellation during synchronous FS ops remains noninterruptible).

`//tests/integration:worker_defaults` passes in **62.2 s** (unforced Build uses worker; body edit reuses 2 / compiles 1; target-only, opt-outs, Restore/Pack/Publish stay non-worker; rerun sync to adopt [automatic defaults](api.md#caching-and-workers)). See [SDK 11 matrix](#sdk-11-platform-qualification). ARM64 does not qualify x64, macOS workers, or RBE. Run `python3 tests/graph_build/acceptance.py OUTPUT --linux-workers`.

## Bounded native regression controls

- **Streaming & publication**: 64 KiB buffers, 1 transfer budget/store (default 8); uploads verify staged payloads, downloads verify streamed digests + deduplicate; up to 2 async publications overlap serial capture and drain before exit.
- **Worker bounds**: 1-hour active deadline, process-tree cancellation, **1,048,576-char** diagnostic tail (with truncation marker; oversized retained replies fail), 1 queued request; fake-child controls pass (synchronous FS ops noninterruptible; full Bazel sandbox cancellation unqualified).
- **Qualification & mappings**: shares content/mode observations within each pre/post-Build phase (never across); immutable multi-owner path index; 63 ProjectSync controls pass on Ubuntu 26.04 x64 / SDK 11.0.100; mapping controls reject duplicate JSON keys and case-ambiguous fields (300 merged/explicit comparisons byte-identical).
- **Shared path & tree helpers**: span-based relative-path validation (10,023 differential paths matched; 10,000 validations: 3,680,000 B → 0 B); `input_integrity.py` passes; shared tree traversal matches all 4 former callers across 32 cases; indexed layout selection + staged ZIP package extraction pass.

Portable controls:

```sh
python3 tests/graph_build/worker_supervision.py
python3 tests/graph_build/publication_queue.py
python3 tests/graph_build/remote_streaming.py
python3 tests/graph_build/remote_publication.py
```

Streaming control fetches eight 8 MiB payloads with budget 2 (see [bounded cache controls](performance.md#bounded-cache-controls)).

## Snapshot materialization defaults

`FileMaterializer` passed XFS reflink and ext4 copy-fallback controls on Linux ARM64 / SDK **10.0.400** (bytes, modes, timestamps, writable isolation, corruption rejection). Default clone mode on XFS passed body/API/Publish replay (**54 / 40 / 23** clones; Publish **64**; unsupported FS falls back to copies). Reproduce: `RULES_MSBUILD_GRAPH_PROFILE=1 python3 tests/graph_build/replay.py` (put `TMPDIR` on reflink FS; `RULES_MSBUILD_GRAPH_COPY_MODE=copy` forces copies).

## Limits

- Persistent workers require Bubblewrap + nested namespaces; broad worker/remote qualification is Linux ARM64 only (x64 source-runtime uses explicit worker strategy; auto x64 workers, macOS workers, and RBE unqualified).
- Unknown SDKs/workloads and whole-repo runtime/native parity are unqualified.
- Custom task/analyzer/generator reads, package side effects, and output ownership require contracts; Build compiler selections do not qualify Pack/Publish.
- Evaluation reuse is opt-in for reviewed compiler-only inputs (verification still reads bytes).
- Sandboxing ≠ graph isolation: build trusted projects; exports reject links; HTTP publication lacks atomic divergent-writer guarantees; test sharding unsupported.

Run suites: `bash scripts/bazel.sh test //tests/integration:SUITE --test_output=errors` (fresh dirs, separate containers for recovery, reports outside Git). See [Contributing](../CONTRIBUTING.md) and the [versioned record](https://github.com/keegan-caruso/msbuild-bazel/blob/fa2764b55f630ae0462e836aa3163b0807f07f7f/docs/support.md).
