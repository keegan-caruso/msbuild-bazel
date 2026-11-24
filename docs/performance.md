# Performance versus raw MSBuild

## Pinned source lifecycle control

Native macOS ARM64 control (Bazel **9.3.2**) installed synthetic Git snapshots of tracked rules source, upgraded A→B, then rolled back B→A (fresh output base per phase, one shared local action cache). Consumer analyzed `msbuild_graph` with a fake SDK and built a marker action: outputs A, B, A; miss, miss, hit. Tests that declared action boundary only (not .NET compilation, graph recovery, or cross-revision project-cache compatibility; no release created).

```sh
python3 tests/tooling/source_distribution_lifecycle.py /tmp/source-lifecycle-run \
  --bazel /absolute/path/to/bazel --disk-cache /tmp/source-lifecycle-cache
```

Writes commit IDs, module files, action logs, and results; shuts down each owned Bazel server. See [pinning and rollback](api.md#pin-update-and-roll-back-the-rules).

## CI comparison controls

`runtime_recovered_tests.py --demo --test-cache=yes` measures normal CI test-result reuse (`--require-test-recovery` requires 9 remote test hits); `--initial-edit=body|api --edit-token=TOKEN` edits before a fresh worker's first build. Default `--test-cache=no` runs actual tests; HTTP cache reachability is checked first so a disconnected cache cannot silently rebuild locally.

Prepare raw inputs with `runtime_full_source.py --prepare-only`, then run `runtime_ci_raw.py --case=body|api --edit-token=TOKEN` (first scored run doubles as full-source correctness control; `--fresh-outputs` clears owned outputs and Restore files, keeping SDK/packages; native binaries and demo helpers are prepared prerequisites). Compare with `runtime_ci_compare.py --case=CASE` (requires matching contracts, edits, compiled bytes, and test outcomes; managed modes follow producer policy: raw `0644`/`0744`, Bazel `0555`, while graph recovery requires exact mode parity). Report executed tests and remote hits separately. CI demos default to top-level downloads; complete artifact verification runs outside the CI timer. See [measured CI results](#runtime-ci-demo).

For pruned source handoffs, `runtime_full_source.py --bootstrap-unused-locks` reconstructs inventory locks outside the declared graph offline (requires all declared locks; verifies retained locks stay identical; reconstructed 5 locks while preserving 260—unscored prep).

## Sync preparation

Multi-root offline sync runs each root's Restore in one native MSBuild invocation (reusing shared dep evaluation/targets; keeping root hooks and per-entry properties; single-root unchanged).

Synthetic roots sharing a 3-library chain (Linux ARM64, 4 CPUs / 6 GiB, SDK **10.0.400**, no external packages; 3 alternating pairs vs **da16128**, fresh private workspaces, medians in seconds; byte-identical JSON/Starlark, later samples run `--check`):

| Roots / projects | Offline sync before → after | With compiler qualification before → after |
| --- | ---: | ---: |
| 1 / 4 | 0.64 → 0.59 | 2.44 → 2.44 |
| 4 / 7 | 2.00 → 0.74 | 5.10 → 3.88 |
| 16 / 19 | 7.66 → 1.24 | 15.67 → 9.36 |
| 64 / 67 | 30.12 → 3.36 | 58.12 → 31.60 |

At 64 roots: offline sync **-88.8%**, qualified sync **-45.6%** (excludes SDK/runner acquisition, NuGet update, and incremental builds; isolates repeated Restore; [runtime preparation](#runtime-preparation) shows private Build as remaining cold cost).

Build each revision's `tools/ProjectSync/ProjectSync.csproj` (`-c Release -o ABSOLUTE_PAYLOAD_DIRECTORY`) with the same pinned SDK, then run (optional trailing root counts; CSV/logs in `FRESH_OUTPUT`; no qualification product reuse):

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK bash tests/project_sync/preparation_benchmark.sh \
  FRESH_OUTPUT BASELINE/ProjectSync.dll CANDIDATE/ProjectSync.dll
```

## Cached preparation

Complete `msbuild_sync(srcs = ...)` snapshots let Bazel reuse qualification across sync/check. Linux ARM64, 4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.0**; same 3-library chain; 3 alternating `bazel run` pairs (median wall s, including publication/check):

| Roots / projects | Ordinary `--check` | Cached `--check` |
| --- | ---: | ---: |
| 1 / 4 | 2.580 | 0.094 |
| 16 / 19 | 9.537 | 0.087 |
| 64 / 67 | 31.887 | 0.094 |

At 67 projects: **-99.7%** with zero qualification executions. Single cold runs (including runner bootstrap, compiling all 67): **34.85 / 34.53 s** (ordinary / cached). Excludes SDK/registry acquisition; native controls confirm source bytes/membership, definitions, props, mappings, producers, and package inventories requalify while unchanged checks reuse.

```sh
RULES_MSBUILD_BAZEL=PINNED_BAZEL bash tests/project_sync/cached_preparation_benchmark.sh \
  FRESH_OUTPUT ABSOLUTE_RULES_CHECKOUT
```

Optional trailing root counts (default **1 / 16 / 64**); set `RULES_MSBUILD_TEST_REPOSITORY_CACHE` for verified acquisition cache and `SYNC_PREPARE_CACHE_URL=URL` to seed a Bazel remote cache. Relocating sources/rules, stopping producer, and running `bazel run //:sync --remote_cache=URL --disk_cache= --lockfile_mode=error -- --check` on a fresh `--output_base` recovered bootstrap and preparation in a 4-project control with zero executions and identical declarations.

### Runtime preparation

Runtime v10.0.0, Linux ARM64, 4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.0**, ~61,000 authored files, **543 configs / 481 compilation nodes** (byte-identical JSON/Starlark to ordinary sync). Isolated cold diagnostic profile with serial qualification (`28b36dc`):

| Phase | Seconds |
| --- | ---: |
| Declared source staging | 5.89 |
| Producer bindings | 5.53 |
| Workspace copy | 8.84 |
| Offline Restore | 20.84 |
| Graph evaluation | 5.88 |
| Private SDK Build | 1,362.47 |
| Sync process total | 1,413.43 |
| Public command total | 1,444.91 |

Private Build is **96.4%** of sync (totals include inventory/publication/cleanup; profile only, not paired speedup). Three unchanged checks: **3.34 / 1.98 / 0.47 s** (zero executions). Ordinary incremental timings unchanged.

32-config Pipelines control matches ordinary sync (body/API, props, mappings, lock-byte edits requalify; unchanged checks reuse; original-state remote recovery matches). JIT control verifies source-runtime reference DLL edits invalidate, restoring recovers, and all 6 upstream tests run.

Run on the source workspace retained by `runtime_downloaded_prepare.py` or `runtime_jit_public_prepare.py`:

```sh
python3 tests/graph_build/upstream/runtime_preparation_cache.py \
  SOURCE_WORKSPACE RESULTS --output-base=FRESH_BASE --cache-url=URL
```

Flags: `--controls` (Pipelines edits), `--producer-controls=SOURCE_RUNTIME` (JIT ref producer), `--profile --reference-contracts=ORDINARY_DECLARATIONS` (cold profile without repeating ordinary Build).

Stopped-producer recovery on relocated 4-CPU / 6 GiB consumer (fresh base, strict lock, no disk cache; single runs including startup/acquisition): full managed prep **17.78 s** (**144 remote hits / 0 executions**, identical declarations); runtime-bootstrap **8.14 s** (**37 hits / 0 executions**). Replayed producer profile lines are not consumer timings.

Live runtime/JIT handoff (4 CPUs / 6 GiB ARM64, SDK 10.0.400, Bazel 9.3.0, single run): prep recovered in **58.13 s** (**227 hits / 0 executions**), unchanged check **2.04 s**; all 5 native producers and managed graphs recovered remotely, 6 JIT tests ran; forced project recovery reused 9 snapshots (0 compilations) and reran 6 tests; bytes/modes matched producer and raw control (recovery qualification, not paired timing). Repeat with `--consumer --seed-report=PRODUCER_SEED` (match `--profile`); close JIT inputs via `runtime_jit_public_consumer.py PREPARED SEED OUTPUT --preparation-base=BASE`.

### Parallel compiler qualification

Private qualification allows up to 4 MSBuild nodes (CPU-bounded; Bazel accounts 4 CPUs / 4 GiB), keeping full SDK Build and input-mutation checks. Linux ARM64, 4 CPUs / 8 GiB, SDK **10.0.400**, vs serial **28b36dc** (alternating pairs, median s; byte-identical declarations):

| Scope | Serial command | Parallel command | Serial private Build | Parallel private Build |
| --- | ---: | ---: | ---: | ---: |
| Synthetic, 17 projects, three pairs | 9.06 | 6.80 | 7.89 | 5.75 |
| Runtime Pipelines, 32 configurations, two pairs | 133.30 | 103.49 | 113.26 | 90.78 |

Pipelines: **-22.4%** command, **-19.9%** private Build (fresh outputs, fixed inputs, OS caches not reset; excludes acquisition, NuGet update, Bazel staging, and incremental builds).

Reproduce synthetic pairs (with built ProjectSync payloads):

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK python3 benchmarks/qualification.py FRESH_OUTPUT \
  --baseline-runner=BASELINE/ProjectSync.dll \
  --candidate-runner=CANDIDATE/ProjectSync.dll
```

Runtime pairs (`RULES_MSBUILD_SYNC_PROFILE=1`):

```sh
PINNED_SDK/dotnet PAYLOAD/ProjectSync.dll SOURCE PINNED_SDK/sdk/10.0.400 \
  src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj \
  --framework net10.0 --package-build --resolve-references --mappings mappings.json \
  --inputs INPUTS.json --runfiles RUNFILES
```

Separate full-runtime direct-CLI profile (**543 configs / 481 compilations**, identical declarations): private Build **1,016.89 s** (**95.9%** of sync), total **1,059.89 s** (vs earlier serial **1,362.47 s**; unpaired profiles; excludes Bazel staging/publication/acquisition; remote-recovery numbers above predate this).

### Project qualification reuse

`qualification_cache = True` adds verified Restore and project snapshots inside a changed preparation action (misses run SDK targets; post-Restore evaluation/validation stay fresh; keys keep conservative dep inputs). See [configuration](api.md#compiler-selections).

#### Qualification-to-Build handoff

`seed_build_cache = True` reuses qualification's compiled products in ordinary Build snapshots. Complete managed runtime graph at `60629d1` (631 configs; Ubuntu 22.04 ARM64, 4 CPUs / 8 GiB RAM + 4 GiB swap, SDK **10.0.400**, Bazel **9.3.0**): cold qualification ran **691 Csc tasks** and seeded **563** assembly snapshots (seed verification/publication **41.11 s**); both Builds below recovered all 563 snapshots (0 misses; matching keys/manifests; separate binlog control recorded **0 Csc/Vbc calls**):

| Consumer state | Bazel wall | Restore action | Graph action | Graph runner |
| --- | ---: | ---: | ---: | ---: |
| New Restore contract | 447.84 s | 408.72 s | 36.07 s | 21.49 s |
| Restore prepared | 40.84 s | Action hit | 35.68 s | 20.91 s |

Tools/packages prepared; Bazel disk/remote caches off (local action cache kept Restore; second run changed cache URL trailing slash to force graph). Single correctness observations, not paired speedups; also declares 63 formerly omitted reviewed evaluation-item files in Build/Restore. Enable on `//:sync` with matching HTTP cache and `app_graph(linux_stable_paths = True)`; see smaller [controls](support.md#project-qualification-cache).

#### Small graph

Linux ARM64, SDK **10.0.400**, 4 CPUs / 6 GiB; 17 projects (1 consumer, 16 producers); 3 alternating unprofiled pairs with distinct edits (seeding excluded); **d1021ba** vs **59d3a79** medians:

| Edit | Fresh Restore | Restore reuse + shared hashing/materialization |
| --- | ---: | ---: |
| Body | 2.42 s | 1.65 s |
| API | 2.39 s | 1.65 s |

Both compile the same 2 projects with identical declarations. [Intermediate diagnostics](https://github.com/keegan-caruso/msbuild-bazel/blob/7eecc63/docs/performance.md#qualification-preparation-reuse) separated Restore reuse from shared hashing/replay (evaluated-state transfer alone showed no small-graph gain; cloning falls back to copies on ext4).

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK python3 benchmarks/qualification.py FRESH_OUTPUT \
  --baseline-runner=BASELINE/ProjectSync.dll \
  --candidate-runner=CANDIDATE/ProjectSync.dll \
  --cached-edits --width=16 --depth=1 --samples=3
```

Use `--profile` separately for phase diagnostics.

#### Runtime graph

Runtime v10.0.0, **543 configs / 481 cacheable projects**, SDK **10.0.400**, Linux ARM64, 4 CPUs / 8 GiB (`59d3a79`). Single direct-CLI profiles on one VM (empty local cache per HTTP row; not paired speedups):

| Case | Total | Restore replay | Private SDK Build | Csc tasks |
| --- | ---: | ---: | ---: | ---: |
| HTTP recovery | 29.99 s | 6.35 s | 3.57 s | 0 |
| HTTP + Pipelines body edit | 47.21 s | 6.66 s | 19.70 s | 7 |
| HTTP + implementation/reference API edit | 59.27 s | 7.47 s | 29.22 s | 17 |

All hit Restore and match ordinary sync JSON/Starlark byte-for-byte. Body edits add `GC.KeepAlive` in `PipeOptions`; API edits add a method in impl/ref. Evaluation **5.65–6.19 s**; source copy **2.70–6.44 s**. SDK hashed once per run; mutable inputs keep pre/post-Build byte checks.

Empty-cache seed: **1,178.71 s** (**611 Csc tasks** + publication; overlapped another VM, not paired). Local replay **31.76 s**, later original-state recovery **23.08 s** (481 hits / 0 Csc; FS cache states differ). Excludes SDK/package acquisition, Bazel staging, and scratch trims. [Earlier fresh-Restore profiles](https://github.com/keegan-caruso/msbuild-bazel/blob/d1021ba/docs/performance.md#project-qualification-reuse) keep the prior baseline.

Reproduce via `runtime_downloaded_prepare.py --slice=runtime-suites` workspace, native manifest, extracted runfiles, and all 39 `entries` from BUILD, adding `--qualification-cache OWNED_CACHE --qualification-cache-url http://cache:8080` (root `restoreReuseInputs` reviews the 2 Pipelines files; fresh cache per HTTP edit; `RULES_MSBUILD_SYNC_PROFILE=1` / `PROJECT_SYNC_CACHE` for diagnostics; keep reports out of Git).

Separate 4-project consumer (with package SDK) recovered Restore + all projects in **1.14 s** with producer stopped and no local cache (0 compilations, identical declarations/digests; RBE unqualified).

## Downloaded-SDK workflow

Runtime v10.0.0, 4 managed roots (Pipelines, Encodings.Web, Json, ComponentModel Primitives): **182 configs / 163 compilations**, **106 archives / 91 native locks**; Linux ARM64, 4 CPUs / 6 GiB, SDK **10.0.400**, Bazel **9.3.0**, default worker budgets, fresh evaluation (unprofiled wall s):

| Case | Raw MSBuild | Graph | Graph reused / compiled |
| --- | ---: | ---: | ---: |
| Cold Restore + Build | 371.24 s | 384.49 s | 0 / 163 |
| No-op | 5.94 s | 0.14 s | Whole action hit |
| Pipelines body edit | 18.36 s | 17.55 s | 158 / 5 |
| Pipelines API edit | 32.59 s | 37.93 s | 147 / 16 |

Cold: 1 run (tools/packages warm, graph bootstrap **29.27 s** separate); incremental: medians of 3 alternating pairs matching all **1,447 DLL/PDB/resource files** (instrumented controls matched **5 / 16** compiler sets; reused Restore; 3 local recoveries **5.85–7.53 s**, 163 hits / 0 compilations; cold/API overhead **+3.6% / +16.4%** without opt-in eval reuse).

Stopped-producer relocated Linux ARM64 recovery: **5.41 s** cached Restore + graph; forced graph **16.11 s** (Restore hit + **163 snapshots / 0 compilations**); both matched all **3,980 retained files/modes** (Bazel-tested app verified source-built Pipelines DLL hash and `Pipe` API). Unscored prep: package update/check **~51 s** each, offline sync/check private Build **598 s**.

Reproduce: [preparation](../tests/graph_build/upstream/runtime_downloaded_prepare.py) (`SOURCE_ARCHIVE OUTPUT`), [benchmark](../tests/graph_build/upstream/runtime_benchmark.py) (`OUTPUT/workspace RESULTS --output-base=FRESH_BASE --slice=loaded-common --samples=3 --memory-gib=6 --cold-build --trim-between-rows`), [complete remote](../tests/graph_build/upstream/runtime_complete_remote.py) (`--phase=producer --cache-url=URL`, relocate, stop producer, `--phase=consumer --seed-evidence=SEED_JSON`), and [consumer smoke](../tests/graph_build/upstream/runtime_downloaded_smoke.py) (`RUNTIME_WORKSPACE FRESH_APP --cache-url=URL`).

## Source SDK production and recovery

Single native Ubuntu 26.04 ARM64 / LLVM 18.1.8 trial (Bazel **9.3.2**) rebuilt VMR `b0f34d51fccc69fd334253924abd8d6853fad7aa` with [rules `4158b03`](https://github.com/keegan-caruso/msbuild-bazel/tree/4158b034e2917990287753f5b2805b6f47b27318). Separate declared inputs: controller SDK **10.0.400**, upstream SDK **10.0.100-rc.2.25502.107**, `Private.SourceBuilt.Artifacts.Bootstrap.tar.gz` (`47f6aea3a4688d24bcb5aee0b8b394398ae8bd7244c8ccabe938bb5dd2a19487`), generated `bootstrap.tar` (`974ca15d1498735faa9ef3fa72d85898358bbded97e68b87d1c5aa142c7078a1`), and sealed-root native archive (`1854d067717cba3afe85c01e166e2a2c7d95c4dafea89e172b69da8b536c874a`; upstream logs selected Clang 18.1.8). Config: 4 CPUs / 8 GiB, 1 Bazel job, `DOTNET_PROCESSOR_COUNT=2`, `BuildInParallel=false`.

| Phase | Wall time | Observed result |
| --- | ---: | --- |
| Upstream source build | 28 min 22.23 s | Actual `SourceSdkBuild` cache miss, SDK 10.0.100 / runtime 10.0.0 |
| Producer Bazel test, including source build | 1,826.669 s | Build and actual smoke test pass |
| Fresh read-only consumer after seed stopped | 727.782 s | All 12 recorded spawns remote hits, including producer and graph |
| Consumer body / API edits | 15.694 / 17.172 s | Graph and tests execute; SDK reused |
| Extra forced smoke test | 12.625 s | Test executes; source SDK does not rebuild |

Upstream time is nested in producer Bazel time; full guardian (prep/export/startup): **2,735.352 s**. New archive: **569,564,274 bytes**, SHA-256 `e043c131f157a4dfd8f66bfe6016b95ee301d0265b075a69b5c84dd9577c45a2`. Consumer copied declared inputs only (oracle excluded, verified against recovered archive). Both used project-cache read-only mode; only seed uploaded Bazel actions. Fixture HTTP cache (6 GiB disk / 2 GiB request limits, 1 connection): **7,431 seed PUTs**, **14,987 consumer GETs / 0 consumer PUTs**, unchanged **2,641,967,172 bytes** (serial SDK-tree downloads; no comparison with older timings).

Producer resources (1,911 samples): min available memory **1,996,292 KiB**, peak summed RSS **6,219,744 KiB** (can double-count shared pages), GNU time max RSS **2,334,916 KiB**, max guest FS **34,674,176,000 bytes** (single cold/recovery trial, not sustained or paired).

Cold consumer with [SDK 11 rules candidate `6760e9f`](https://github.com/keegan-caruso/msbuild-bazel/tree/6760e9f637e257b2c2d070c908dbbd24900a3a5a) (controller SDK 11.0.100) and this archive alone (SDK 10.0.100 / runtime 10.0.0) passed package/Razor tests and ran the published app (`SourceSdk.Package` 1.0.0, `lib/net10.0/Package.dll` SHA-256 `3fa898a68359711ef6f576b044dde2feb0a840678bfdb4eb899fc92bfd24bb10`; no component-bundle overlay or source rebuild; guest-local outputs, non-overlapping mounts). See [qualified scope](support.md#source-toolchains-and-nativeaot), [producer](../tests/source_sdk/source_action_prepare.py), [recovery driver](../tests/source_sdk/source_action_recovery.py), and [consumer scenarios](../tests/source_sdk/consumer_scenarios.py).

Compact evidence reconstruction from retained SDK 11.0.100 ARM64 producer logs: **289,986,560 bytes** full vs **81,920 bytes** compact (archive-size comparison only, not a new run/transfer timing; keeps bounded log tails, timing, and SDK info; opt into full successful logs with `--full-diagnostics`).

## Fresh .NET 11 VMR smoke-test recovery

[Linux ARM64 VMR recipe](../tests/source_sdk/LINUX_ARM64_11.md#recover-the-sdk-and-exercise-consumers) supports Bazel top-level output downloads so `//:smoke` leaves the SDK archive and compiler layouts remote.

Bazel 9.3.2, Ubuntu 26.04 ARM64, 4 CPUs / 6 GiB, same stopped source-produced SDK 11.0.100 / runtime 11.0.0 seed; 1 remote connection, no uploads/disk cache, forced test execution, fresh workspace/output base/output user root per run (timers cover Bazel invocation only; order: top-level/all, all/top-level, top-level/all):

| Pair | All outputs | Top-level outputs | Speedup |
| --- | ---: | ---: | ---: |
| 1 | 905.8 s | 74.7 s | 12.1× |
| 2 | 945.1 s | 71.9 s | 13.1× |
| 3 | 901.1 s | 71.6 s | 12.6× |

Median paired speedup: **12.6×** (all 6 ran on runtime 11.0.0 with identical SDK digest; only full-download materialized the SDK archive; fresh smoke against populated cache only—SDK production and local compilation need different inputs).

First top-level run had two identical copies of the 333 shared-framework files (launch helper + app runtime; Core **184.0 MiB**, ASP.NET Core **25.7 MiB** uncompressed); test process took **76 ms**; pairs 2–3 profiles attributed **48.93 / 48.32 s** to remote input staging starting ~21 s in (profiles do not measure wire bytes).

Pinned ARM64 .NET 11 console fixture now splits Core and ASP.NET directories: console runtime **200 files / 197,231,823 bytes** vs full **335 files / 224,128,104 bytes** uncompressed (all 200 common files match SHA-256/mode; console loads CoreLib from smaller layout, web probe loads ASP.NET Core from full layout and is rejected by smaller layout).

Historical download/launcher A/B requires the classic launcher ([pinned commands](https://github.com/keegan-caruso/msbuild-bazel/blob/7a6d573/docs/performance.md#compare-smoke-launchers)). Current recovery profile: `source_action_recovery.py --smoke-only --download-outputs=toplevel --remote-connections=8 --profile`.

### Native debug sections and the module lockfile

The pinned VMR11 ARM64 smoke uses a stripped Core runtime. Both runtime trees contain 200 files. The original occupies 197,231,823 bytes and the stripped tree 89,668,975 bytes. CoreCLR alone falls from 46.88 to 6.71 MiB and the JIT from 19.88 to 3.20 MiB. All non-ELF files, file modes, loaded ELF section bytes and GNU build IDs matched. GNU strip normalized the initializer/finalizer array entry size in some ELF section headers. Use `//:console_runtime` for the original native debug sections.

On the retained SDK archive, the first successful strip-and-upload seed took 162.51 s, including 141.81 s in the HTTP cache upload span. Two earlier seeds at eight connections timed out uploading blobs. Seeding at one connection with `--remote_timeout=180s` completed. The read-only recovery trials used eight connections, Bazel 9.3.2, four CPUs and 6 GiB in one Ubuntu 26.04 ARM64 guest. A declared copy of the retained SDK archive replaced source production. Each trial verified the archive digest, every non-test action hit and forced execution on runtime 11.0.0.

With the same prepared install and repository caches and lockfiles disabled on both sides, the smaller runtime alone reduced median `TestRunner` remote input staging from 8.84 to 5.33 s and median invocation wall time from 14.11 to 11.42 s over three alternating pairs. Logical runfiles fell from 197,251,523 to 89,688,684 bytes (206 files in both).

For the module-lock control, three alternating `build //:smoke --nobuild` pairs used fresh analysis roots and the same prepared Bazel install and repository caches. Reading the producer lockfile with `--lockfile_mode=error` reduced median main-repository mapping from 2.28 to 0.21 s and analysis-only invocation wall time from 3.93 to 2.09 s. Reusing the install and repository caches alone with lockfiles disabled gave no consistent end-to-end gain in a separate three-pair control.

With empty install, repository, workspace and Bazel output roots for every trial, the previous smoke fixture and the new stripped, locked fixture gave these wall times. The producer was stopped and uploads and the disk action cache were disabled.

| Pair | Previous smoke | Stripped, locked smoke |
| ---: | ---: | ---: |
| 1 | 17.17 s | 13.90 s |
| 2 (reversed) | 16.44 s | 13.96 s |
| 3 | 16.67 s | 13.99 s |

Median wall time fell **16.67 → 13.96 s** and median staging **8.32 → 5.31 s**. With empty repository caches, median module mapping was **2.16 → 1.92 s**. Reproduce the optimized smoke with the [ARM64 recovery recipe](../tests/source_sdk/LINUX_ARM64_11.md#recover-the-sdk-and-exercise-consumers), adding `--remote-connections=8 --profile` to the locked recovery command.

### Retained-archive launcher and connection control

Ubuntu 26.04 ARM64, Bazel 9.3.2, 4 CPUs / 6 GiB, retained SDK 11.0.100 / runtime 11.0.0 archive (`993765849ca1f97d64ca1a157b34158b37dc75facff43d41707365dc8724ec85`), archive-copy action replacing `SourceSdkBuild`, rules at `6608ac6` (independent of source production/historical producer key). Three paired trials per launcher/connection cap (fresh workspace/output base/output user root, top-level downloads, no disk cache/uploads, forced test, all non-test actions hit HTTPS cache via UNIX-socket relay; order reversed for pair 2; profiles enabled in all trials):

| Connections | Pair | Classic wall / staging | Direct wall / staging | Wall speedup |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 54.32 / 45.16 s | 30.81 / 22.81 s | 1.76× |
| 1 | 2 | 50.62 / 42.32 s | 31.11 / 22.56 s | 1.63× |
| 1 | 3 | 51.72 / 42.89 s | 30.24 / 21.77 s | 1.71× |
| 8 | 1 | 22.77 / 14.03 s | 16.21 / 8.06 s | 1.40× |
| 8 | 2 | 23.71 / 15.55 s | 16.04 / 7.74 s | 1.48× |
| 8 | 3 | 25.12 / 16.37 s | 16.06 / 7.88 s | 1.56× |

Medians: classic/direct **1.71×** (1 conn) / **1.48×** (8 conn); 1 vs 8 conn **2.13×** classic / **1.90×** direct; direct + 8 conn vs classic + 1 conn **3.22×** (**51.72 → 16.06 s** wall, **42.89 → 7.88 s** `TestRunner` staging; direct medians **30.81 / 16.06 s** wall, **22.56 / 7.88 s** staging; includes profiles and fresh Bazel install overhead; setup/extraction/seed excluded). Prefer 8 connections for this smoke setup (does not qualify other workloads or change global defaults). Logical runfiles (not wire traffic): classic **681 files / 448,503,210 bytes**, direct **341 files / 224,145,656 bytes** (both still included Core + ASP.NET Core; every trial verified cached archive digest, graph hit, and runtime 11.0.0 output). Reproduce via [pinned driver](https://github.com/keegan-caruso/msbuild-bazel/blob/7a6d573/docs/performance.md#retained-archive-launcher-and-connection-control) at `7a6d573` with rules at `6608ac6`.

## Retained source SDK consumer recovery

Ubuntu 26.04 ARM64, Bazel **9.3.2**, historical Ubuntu 22.04 source-built SDK 10.0.100 / runtime 10.0.0 archive (`dc795ffff8b6b3c2adac341c844ca71116cb2144c4c745ee2bc9f52a60836345`) declared via `msbuild_sdk` (no source producer). Cold consumer packed NuGet package, ran consumer + Razor tests, and published/ran an app. Stopped seed guest → fresh guest (empty base, uploads off, project-cache read-only, 4 CPUs / 6 GiB, 2 jobs, 1 local test, `--remote_max_connections=8`) recovered SDK layout, Pack, extraction, graph, and Publish layout over HTTP, forcing both tests. Package (`b7a4cd4fccea6be8522d63b6e97bbaa9d7d02068293004fb1a50b05e2d498773`, identity/version/DLL verified) and 4 published-file hashes matched; cache size unchanged (request-level PUTs unmeasured; prior uncapped seed hit TLS handshake timeouts). Same-host consumer control via [consumer driver](../tests/source_sdk/consumer_scenarios.py) (not producer recovery, cross-host, SDK 11, or benchmark; required guest-local workspace/outputs for archive symlinks in Apple Container).

## Reviewed evaluation reuse

163-compilation downloaded-SDK slice opting into the 2 reviewed Pipelines body/API sources (3 alternating unprofiled pairs/mode, 4 CPUs / 6 GiB, 512 MiB eval budget, HTTP project cache):

| Edit | Retained graph | Fresh graph | Raw paired with retained |
| --- | ---: | ---: | ---: |
| Body | 16.26 s | 18.84 s | 18.98 s |
| API | 31.06 s | 42.62 s | 35.85 s |

Fresh-control raw medians: **19.47 / 33.46 s**. Retention saved **2.58 / 11.55 s** vs fresh graph; retained API **-13.4%** vs paired raw. All **1,447 required files** matched; reused Restore + all 182 evaluations, compiling the same **5 / 16** projects (separate profiled controls verified compiler sets, excluded from scores). Separate API profiles: eval **1.83 → 0.22 s**, input hashing **0.92 → 0.45 s**, replay **2.05 → 1.37 s**, publication **~0.06 s** (overlapping, not paired).

Prepare: `runtime_downloaded_prepare.py SOURCE_ARCHIVE OUTPUT --evaluation-reuse`. Compare: `runtime_benchmark.py --slice=loaded-common --qualified-raw-results=PRIOR_RESULTS --evaluation-reuse --compare-fresh-evaluation --project-cache-url=URL --memory-gib=6 --samples=3 --diagnostics --trim-between-rows` (separate workspace with reviewed `EvaluationReuseInputs` and output base; enforces identical raw/graph semantics). See [evaluation contracts](api.md#caching-and-workers).

## Large downloaded-SDK graph

**39 roots / 543 configs / 481 compilations** (**141 package archives / 265 native locks**); runtime v10.0.0, Linux ARM64, 4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.0**, HTTP project cache, 4 MSBuild nodes; 3 alternating unprofiled pairs (medians):

| Case | Raw MSBuild | Graph | Graph reused / compiled |
| --- | ---: | ---: | ---: |
| No-op | 17.89 s | 0.26 s | Whole action hit |
| Pipelines body edit | 31.65 s | 26.49 s | 475 / 6 |
| Pipelines API edit | 46.00 s | 41.39 s | 464 / 17 |

Body/API **-16.3% / -10.0%** vs raw; all **3,622 DLL/PDB/resource files** match; separate instrumented controls matched compiler sets (**6 / 17**); reused Restore + all 543 evaluations. Three local recoveries: **17.69–19.89 s** (481 hits / 0 compilations). Needs explicit **1024 MiB evaluation budget** (profile measured **676.7 MiB** managed memory; default 512 MiB retired evaluations). Single cold Restore + Build: **1086.80 s** (Restore **84.88 s**, graph **990.34 s**, excluding bootstrap; no new paired cold result; retains disposable intermediates, so file counts/edits differ from LINQ baseline). Earlier source-only prep (unpaired, outside incremental scores): NuGet update/check **147.19 / 175.91 s**, ordinary sync/check **1526.98 / 1469.58 s** (see [runtime preparation](#runtime-preparation)).

Relocated 4-CPU / 6 GiB consumer (producer stopped, default 512 MiB budget, acquisition/bootstrap separate): normal Restore + graph recovery **8.83 s**; forced graph **30.28 s** (Restore remote hit + **481 HTTP hits / 0 compilations**); both matched **10,780 retained files/modes**.

Current-code correctness refresh (8 GiB producer → stopped → 6 GiB consumer, test caching off): executed app + all 8 suites after normal remote hits and after forced **481 HTTP hits / 0 compilations**; both matched all **10,780 files/modes**, **118,952 passed / 64 skipped** cases, **96 loaded-runtime observations**, and earlier producer's full byte/mode inventory (correctness control, not paired timing).

Reproduce: `runtime_downloaded_prepare.py SOURCE_ARCHIVE OUTPUT --slice=runtime-suites --evaluation-reuse --evaluation-cache-mb=1024`, then `runtime_full_source.py`, `runtime_benchmark.py --slice=runtime-suites --qualified-raw-results=RAW_RESULTS --evaluation-reuse --samples=3 --memory-gib=8 --project-cache-url=URL --diagnostics --trim-between-rows`, `runtime_complete_remote.py` (recovery), or `runtime_recovered_tests.py WORKSPACE RESULTS --phase=producer --output-base=FRESH_BASE --cache-url=URL --host-space-path=HOST_BIND` (then relocate, stop producer, `--phase=consumer --seed-report=PRODUCER_RESULTS/seed.json`). See [runtime support](support.md#downloaded-sdk-and-runtime-sources).

### Runtime CI demo

Recorded timings use the earlier Ubuntu 22.04 / Clang 14 producer; current setup uses Ubuntu 26.04 / Clang 18.1.8 (not re-timed).

Runtime v10.0.0 (`60629d1`), SDK **10.0.400**, Bazel **9.3.0**, runner `95368b8b…`, Linux ARM64, 4 CPUs / 6 GiB/worker, private HTTP cache, stopped producer, relocated source-only consumer, fresh output bases. Scope: **39 roots / 543 configs / 481 compilations** (source-native binaries, SDK/packages, helpers prepared; fixed version inputs; bounded slice, not full upstream CI):

| Unchanged job | Restore/build | Tests/results | Total CLI |
| --- | ---: | ---: | ---: |
| Raw MSBuild, fresh outputs | 1,030.76 s | 90.37 s, nine actual targets | 1,121.13 s |
| Bazel, download all | 32.01 s | 1.20 s, nine remote test hits | 33.21 s |
| Bazel, top-level downloads | 19.42 s | 1.01 s, nine remote test hits | 20.43 s |
| Bazel, top-level + batched layouts | 13.15 s | 0.99 s, nine remote test hits | 14.15 s |

Raw: 1 run; first two Bazel rows: medians of 3 alternating pairs (ABBAAB); batched: median of 3 fresh-base runs (excludes interphase checks). Zero executions (including Restore + 5 native producers): **309 spawns** before batching, **186** after (`msbuild_graph_layouts` replaces **124** host exports with one manifest action; matches **490 legacy files/modes**). Top-level downloads cut CLI time **-38.5%** (separate diagnostic cut overlapping remote-download spans **8.83 → 0.70 s**; optional audit downloads add **21.16–21.52 s** before / **13.94–14.38 s** after, outside CI timer).

With runner **`039b9ced…`** (parallel staging; 3 alternating fresh-worker body-build pairs; 8 GiB producer; unique body edits, **475 hits / 6 compilations**, reference bytes + **10,780 modes** preserved; tests/audits/JSON log/profiling off):

| Download policy | Median build CLI | Range |
| --- | ---: | ---: |
| All outputs | 62.11 s | 61.63–63.49 s |
| Top-level outputs | 56.61 s | 56.31–57.18 s |

Saves **5.49 s / 8.8%** by leaving expanded NuGet trees remote (separate JSON control: **57.86 s**, 0 Restore/native executions; audit selects graph, native products, and `runner` output group). Revised demo passed whole-action recovery + body edit with **9 actual test targets / 118,952 passed / 64 skipped** + restoration (matched archived raw's **3,622 compiled files**; JSON build **60.71 s**, tests **91.66 s**, targeted audit **2.12 s** whole / **0.56 s** local).

Earlier single edit observations (runner `95368b8b…`), **raw retained outputs** vs **fresh Bazel worker**:

| Edit | Raw build/publication | Bazel build | Actual tests, raw / Bazel |
| --- | ---: | ---: | ---: |
| Pipelines body | 29.88 s | 67.29 s | 89.47 / 92.75 s |
| Pipelines API | 45.20 s | 76.86 s | 93.67 / 89.11 s |

Bazel reused **475 / 464** and compiled **6 / 17** (0 Restore; all 9 test targets matched **3,622 DLL/PDB/resource files**, **118,952 passed / 64 skipped**, and **10,780 retained files/modes**; body edits preserve ref bytes; fresh-worker overhead remains significant). Separate body-edit profile (475 hits / 6 compilations): worker **39.06 s** = staging **6.00 s** + child **32.52 s** (eval **7.32 s**, Restore validation **3.30 s**, exec/recovery **18.64 s**) + verify/publish/cleanup **0.54 s** (diagnostic, overlapping).

Parallel broker staging (≤4 copies; 3 alternating isolated pairs auditing **19,319 files / 2.21 GB** outside timer): page caches dropped **5.82 → 3.89 s** (**-33.1%**); warm **1.69 → 1.36 s** (child replaced by audit; does not establish new end-to-end time). Reproduce in disposable Linux VM:

```sh
python3 tests/graph_build/worker_staging.py /tmp/new-staging-results \
  --execroot=EXECROOT --request=GRAPH_REQUEST_JSON \
  --runner=BASELINE/GraphBuild.dll --runner=CANDIDATE/GraphBuild.dll --cold
```

Normal test recovery needs `runtime_recovered_tests.py --phase=producer --test-cache=yes` before stopping producer (new setups seed cached tests and default to cached-CI mode requiring 9 remote hits; `--test-cache=no` forces execution).

Setup on Apple silicon Mac (Git, Python 3, Apple Container; **60 GiB free** + network for cold setup):

```sh
python3 scripts/setup-runtime-demo.py /absolute/runtime-demo
bash /absolute/runtime-demo/run.sh /tmp/runtime-demo-1
# Execute all nine targets instead of recovering test results:
bash /absolute/runtime-demo/run.sh /tmp/runtime-demo-actual --test-cache=no
# Include recovery, tests, a unique body edit, tests again and restoration:
bash /absolute/runtime-demo/run.sh /tmp/runtime-demo-2 --body-edit --test-cache=no
# Continue an interrupted setup from its frozen inputs:
python3 scripts/setup-runtime-demo.py /absolute/runtime-demo --resume
# Verify the retained handoff and remove the stopped producer VM:
python3 scripts/setup-runtime-demo.py /absolute/runtime-demo --archive-producer
```

Setup builds an Ubuntu 26.04 / Clang 18.1.8 image, records digest/package inventory, downloads verified sources/tools, updates NuGet, qualifies the 39-root graph, declares 5 native producers, composes source runtime/app + 8 suites, seeds build/test results, transfers a manifest-verified input checkpoint, stops producer, and creates an independent consumer (acquires SDK/packages/runner without building Restore/graph; private cache uses a stable alias). `setup.json`, frozen rules, checkpoint, seed, inventories, and logs stay in the setup dir (keep in durable storage; resume uses snapshot; `--archive-producer` verifies before deleting stopped VM; runs verify stopped/archived producer, use fresh bases, restore edits and delete base on success, keep on failure; existing `--test-cache=no` setups need fresh setup for cached test recovery; no GitHub CI).

Options: `--image=IMAGE@sha256:DIGEST`, `--cache-url=URL`, `--prepared-inputs=FILE --prepared-sha256=HASH` (**32 GiB free** with external cache; export via `runtime_demo_prepare.py pack --workspace=WORKSPACE --archive=INPUTS.tar.gz`).

Clean setup passed on Linux ARM64 (fresh image, downloaded sources, empty private cache, resumed after deliberate interruption, verified producer deletion): consumer recovered **309 build spawns / 0 executions** in **28.93 s**, ran all 9 targets in **91.55 s** (**118,952 passed / 64 skipped**, **10,780 files/modes**); command **122.37 s** including checks, post-run verification **1.09 s** (single observation, not paired; cold setup excluded). All 20 tooling controls passed (including archive integrity, retirement guards, post-deletion resume, and changed-seed rejection).

## Compilation model comparison

Graph/plugin is the sole backend. A retired native-batch experiment put the Pipelines closure in one action, rebuilding unchanged projects on edit. Runtime v10.0.0 (`60629d1`), **28 project paths / 42 configs / 38 compilation nodes**, SDK **10.0.400**, Bazel **9.3.0**, Linux ARM64, 4 CPUs / 6 GiB; single unprofiled CLI runs (seconds, identical configured graphs):

| Case | Raw MSBuild graph | Graph/plugin | Retired native batch |
| --- | ---: | ---: | ---: |
| Fresh Restore + Build | 225.41 | 206.38 | 220.41 |
| Pipelines body edit | 18.55 | 17.13 | 148.16 |
| Pipelines API edit | 21.96 | 21.24 | 146.78 |

Cold runs clear outputs/packages and Bazel action/worker state (acquisition, sync, bootstrap, trim unscored); edits keep local state, no remote cache/profiling/tests; raw uses MSBuild graph API with 4 nodes and stable paths; all deps source-built. All match **412 DLL/PDB/resource files** (SHA-256; body keeps ref bytes, API changes them; 0 Restore on edit). Plugin keeps 42 evaluations and rebuilds **6 / 11** projects (body binlogs: 6 `CoreCompile` in both raw and plugin); native batch rebuilds 38 main + 39 localized satellite assemblies (**8.6× / 6.9× slower**; single observations; earlier 17.5% projection did not hold; backend removed).

## Paired runtime baseline

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`): **260 paths / 543 configs / 481 compilations / 39 roots**; Linux ARM64, 4 CPUs / 8 GiB, SDK 10.0.400, Bazel 9.2.0, 4 MSBuild nodes, 1 worker; complete compiler inventories at **b3cf505**, 8192 MiB project cache, 1024 MiB eval budget (larger than [production defaults](api.md#caching-and-workers)). Three alternating unprofiled pairs (median wall s):

| Case | Raw MSBuild | Graph | Reused / compiled projects |
| --- | ---: | ---: | ---: |
| No-op | 17.63 s | 0.29 s | Whole Bazel action hit |
| LINQ body edit | 22.24 s | 18.11 s | 480 / 1 |
| LINQ API edit | 154.84 s | 129.83 s | 434 / 47 |

Body/API **-19% / -16%** vs raw; identical compiled sets and all **2,814 required DLL/PDB/resource files** (bytes; graph publishes read-only); reused 543 evaluations + Restore. Three local recoveries: **18.44–20.84 s** (481 hits / 0 compilations). Acquisition, seeding, priming, comparison, trimming unscored; failed attempts excluded.

Earlier paired cold Restore + Build (`8d83f0f`): graph **1061.33 s** vs raw **1056.91 s** (+0.4%, matching 3,622 then-published products; SDK/packages/bootstrap warm; predates latest contracts; no new paired cold result for complete inventories).

<a id="wider-evaluation-reuse"></a>
<a id="evaluation-correctness-controls"></a>
<a id="optional-replay-intermediates"></a>

## Improvements

| Removed work | Measured result | Scope |
| --- | --- | --- |
| Unselected compiler edges | LINQ body/API graph compiler calls fell from 146/150 to 1/47, matching raw | Complete inventories; separate profiles, not paired medians |
| Repeated evaluation | Pipelines body/API evaluation fell from 5.75/5.53 s to 1.64/1.73 s | Separate profiles; fresh project instances still required |
| Duplicate replay/publication | 808 disposable `obj` DLL/PDB files, 93 MB omitted; 2,814 required products retained | Snapshots still store and verify omitted bytes; no isolated end-to-end speedup |
| Dependency reread after replay | Hash + copy + dependency hash median 1.43 → 0.87 s | Six warm isolated pairs, 10,780 files / 697 MB |
| Duplicate preparation hash | Materialization median 1.77 → 0.59 s | Five warm isolated pairs, 8,979 files / 1.75 GB; child still verifies |
| Serial child verification | Warm/cold medians 1.23/5.37 → 0.58/3.84 s | Six warm / three cold isolated pairs; up to four hash threads |

Combined fingerprints stream JSON into `IncrementalHash` (compatibility/corruption controls passed; no material verification speedup; read-only binds/timestamps/inodes never replace byte verification). Generic sync (`4bc0cd2`) reproduced all **2,970** reviewed compiler selections (1 validation pair: 1/47 compiled, 2,814 files, 481 snapshots; extends correctness, not paired baseline).

## Complete remote-cache recovery

At **bee52f6**, relocated Linux ARM64 consumer (producer stopped, fresh bases, Bazel HTTP cache, no disk cache) recovered the 481-compilation graph (single unprofiled runs):

| Case | Wall time | Restore | Graph |
| --- | ---: | ---: | ---: |
| Whole-action recovery | 8.32 s | Remote hit | Remote hit |
| Forced graph execution | 28.99 s | Remote hit | 481 project hits / zero compilations |
| Pipelines body edit | 26.64 s | Reused | 475 hits / six compilations |
| Pipelines API edit | 39.82 s | Reused | 464 hits / 17 compilations |
| Compiler failure recovery | 31.02 s | Reused | 475 hits / six compilations |

All **9,972 retained files** matched bytes/modes (omissions verified); edits reused 543 evaluations (compiler failure reset them); spawn logs verify recovery (earlier 95.65 s Restore disabled Bazel action cache; recovery ≠ RBE). Separate stopped-producer control with Bazel action caches disabled: **481 HTTP hits / 0 compilations**, 9,972 files, **124.17 s** total (**17.06 s** profiled runner; correctness control only).

### Source-runtime product

#### Ubuntu 26.04 / LLVM 18 qualification

Ubuntu 26.04 ARM64, 4 CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.2**, Clang **18.1.8**. After a host interruption stopped the first final managed Build, supported resume reused all 3 native producers and finished the managed product, archive (22 MiB), and forced consumer tests:

| Phase | Observed wall time | Method / cache state |
| --- | ---: | --- |
| Initial managed preparation / qualification | 1,274.60 s | Separate initial phase; sync 1,118.92 s, sync-check 3.36 s |
| Resumed managed graph | 1,093.20 s total / 1,078.88 s execution | 563 project misses, zero hits; MSBuild execution, not pure Csc CPU time |
| Whole resumed Build stage | 1,474.28 s | Includes repeated offline 172-root Restore, managed graph above, layout/archive; native outputs cached |
| Forced consumer verification | 36.26 s | Two actual tests: app 0.2 s, runtime/product 34.2 s |

194-package compiler root passed C/C++ compile/link/run; product tests verified 172 framework members, bytes/modes, SDK-absent execution, and CoreCLR-removal rejection (no uninterrupted total or comparison to historical warm timings; see [support](support.md#complete-source-runtime-product)).

#### Complete-product Pipelines body edits

Ubuntu 26.04 ARM64 source runtime + app, SDK 11.0.100, Bazel 9.3.2, net10 source product at [rules `ae39665`](https://github.com/keegan-caruso/msbuild-bazel/tree/ae3966592cb1294d7f1af6f290ab91a8b5ab34e9). Apple Container configured 4 CPUs / 12 GiB (guest reported 5 online CPUs); fresh input-only workspace/base, seeded remote actions, remote project-cache read-only, no Bazel uploads; 1 build job, 1 local test, 1 worker/key (2 stable broker processes). Baseline populated local project cache (not cold):

| Phase | Wall time | Project-cache results |
| --- | ---: | --- |
| Baseline | 1,483.45 s | 0 hits / 563 misses |
| Five body edits | p50 88.44 s; p95 100.65 s | 554 hits / 9 misses in every edit |

Nearest-rank p95 = max of 5. Every case ran app + runtime tests (5 owner variants; 9 aggregate misses do not identify which variants missed; stable brokers, Pipelines ref DLL, native outputs, and CoreLib; each edit built a distinct impl DLL verified in normal and SDK-absent runs; private probe/marker fixture; not paired vs raw). At 0.5 s sampling: min available memory **4.89 GiB** (baseline) / **6.99 GiB** (edits), 0 OOM; max workspace + base **7.80 GiB**. [Trial harness](../tests/graph_build/upstream/README.md) inputs: mappings `cafe5a24781427a70d25e43d538969fadd21a5fe9e9047263b98ad9b23af01cf`, corrected harness `40fe40321b73286914d830843f139fd6cf9468367bc5775294f181d99235e613` ([PR #204](https://github.com/keegan-caruso/msbuild-bazel/pull/204)).

#### Historical Ubuntu 22.04 qualification

Ubuntu 22.04 ARM64, 4 CPUs / 8 GiB, SDK 10.0.400, Bazel 9.3.0; 172-assembly / 16-native-file developer runtime:

| Phase | Wall time | Cache state |
| --- | ---: | --- |
| Initial sync / sync-check | 1,200.00 / 3.46 s | Fresh qualification / retained preparation |
| Declared runtime + app build | 225.27 s | Native compilation; 563 managed project hits |
| Producer tests | 37.40 s | Two actual test executions |
| Independent build recovery | 75.70 s | 138 remote spawn hits; one local package extraction |
| Consumer tests | 6.67 s | Two actual test executions |

Stopped-producer consumer received **10,025 declared inputs** (16 MiB compressed) + rules/hashes (3 graph actions, Restore, 3 native builds, version gen hit; all **649 runtime files** and archive match; single-run control, not paired/cold speedup). Profiled replay with warm acquisition caches: **51.06 s** (source extraction **11.26 s**, package assembly **~4.2 s**). With reproducible SDK/source repos and downloader disabled: **34.63 s** (0 re-extractions vs **8.83 s** source / **5.37 s** SDK with contents cache off; overlapped validation, use extraction counts not wall times).

Source-only sync consumer (**60,958 authored/control files**, 91 MiB compressed, stopped producer): recovered prep in **35.64 s** (122 remote hits incl. `MSBuildSyncPrepare`, 0 executions, identical declarations; `sync --check` passed forbidding misses).

Cold-seed qualification profiles (HTTP project cache on, Bazel action caches off):

| Qualification case | Bazel wall | Private SDK Build | Project hits | Csc tasks |
| --- | ---: | ---: | ---: | ---: |
| Empty project-cache seed | 1,316.98 s | 1,171.65 s | 0 | 691 |
| Fresh output base, unchanged sources | 90.39 s | 3.50 s | 563 | 0 |

Fresh-base control recovered Restore in **9.43 s** without executing it (single profiles; [earlier forced-edit profiles](https://github.com/keegan-caruso/msbuild-bazel/blob/aa6749b/docs/performance.md#source-runtime-product) also changed an unused input).

Pipelines edits (3 alternating unprofiled pairs, same VM/SDK/runner, Bazel action caches off; conservative Restore keys vs 2 reviewed compiler-content exemptions; medians):

| Edit | Conservative Restore | Reviewed Restore reuse | Reduction | Csc tasks in both |
| --- | ---: | ---: | ---: | ---: |
| Body | 154.21 s | 89.65 s | 41.9% | 11 |
| Implementation/reference API | 158.53 s | 102.58 s | 35.3% | 26 |

Distinct equivalent edits; every candidate reused Restore and every baseline ran it; byte-identical JSON/Starlark; restoring sources recovered Restore + 563 projects (0 Csc). Reproduce on retained `managed/source` workspace with `qualification_cache` enabled (`--trim-between-rows` needs trim permission):

```sh
python3 benchmarks/runtime_qualification.py OWNED_RUNTIME_SOURCE FRESH_RESULTS \
  --mappings=sync-mappings.json --output-base=FRESH_BASE \
  --cache-url=http://cache:8080 --samples=3 --trim-between-rows
```

Source-runtime setup's `--cache-url` enables this; standalone prep uses `--qualification-cache` + `RULES_MSBUILD_PROJECT_CACHE_URL`. Preparation handoff: `runtime_product_recovery.py close-sync SOURCE HANDOFF/workspace --preparation-base=FRESH_BASE` (use `--experimental_remote_require_cached` on consumer).

[Recovery helper](../tests/graph_build/upstream/runtime_product_recovery.py): `close WORKSPACE HANDOFF/workspace` and `seed WORKSPACE HANDOFF/seed.json`; transfer with matching rules as `HANDOFF/rules`; stop producer; in relocated workspace run `scripts/bazel-launcher.sh` with fresh output base, `--disk_cache=`, same `--remote_cache`, `--remote_cache_async=false`, `--remote_download_outputs=all`, `--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=URL`, `--strategy=MSBuildGraph=worker`, `--worker_sandboxing`; build `//:app //:runtime_package` with `--execution_log_json_file=ACTIONS`; run `check WORKSPACE RESULT --seed=HANDOFF/seed.json --actions=ACTIONS`; run `//:app_test //:runtime_test --nocache_test_results`. See [qualified Linux environment](support.md#complete-source-runtime-product).

## Bounded cache controls

- `remote_streaming.py` (macOS ARM64, SDK **10.0.400**): 8 concurrent 8 MiB fetches, store budget 2 → managed-memory growth **3,359,440 bytes** (distinct) / **2,141,080 bytes** (shared), max **2** active responses; shared needed 1 GET; interrupted body recovered on retry (excludes server/native memory and build work; not RSS budget/speedup).
- `publication_queue.py`: capture continues with 2 active publications, admission blocks at capacity, failures drain started work, concurrent distinct-key HTTP puts share 1 payload PUT (concurrency control, no wall-time claim).
- Ownership index (`python3 -m unittest discover -s tests/project_sync -p test_input_observations.py -v`): **7.43 / 19.92 / 52.13 ms** at **1,000 / 4,000 / 16,000 nodes** (vs **999,000 / 15,996,000 / 255,984,000** ordered pairs in prior algorithm; operation counts, not timed baseline).
- Layout expansion (`python3 tests/analysis/runtime_layout_scaling.py`): 1,000→10,000 files and 101→1,001 selections required 3,000→30,000 prefix probes, preserving nested order (isolates prefix selection only).
- Package extraction (128 MiB uncompressed, macOS `/usr/bin/time -l`): **69,484,544 bytes** peak RSS, exact payload parity (adds temp disk I/O while removing whole-archive managed buffers; no baseline/timing claim).

## Reproduce

Sync diagnostics: `bazel run //:sync --action_env=RULES_MSBUILD_SYNC_PROFILE=1` (off by default; `PROJECT_SYNC_PROFILE` totals overlap; check exec log since remote hits replay producer lines). Match source, properties, compiler sets, packages, Restore/cache state, native products, and resources; keep profiling off for scores; report hits/misses, compiler calls, byte parity, and whether acquisition was timed; keep reports out of Git (`--trim-between-rows` for unscored thin-disk trim).

- [Preparation](../tests/graph_build/upstream/runtime_prepare.py): `python3 tests/graph_build/upstream/runtime_prepare.py SOURCE FEED WORKSPACE --slice runtime-suites --prepared-restore --resolve-references`.
- [Paired edits](../tests/graph_build/upstream/runtime_benchmark.py): matching `--qualified-raw-results RAW_RESULTS`, reviewed `--reference-bindings BINDINGS` (from [binding preparation](../tests/graph_build/upstream/runtime_reference_bindings.py)), `--samples 3 --evaluation-reuse --replay-omissions`, [six-file evaluation inventory](../tests/graph_build/upstream/runtime_evaluation_inputs.json), [LINQ edit case](../tests/graph_build/upstream/runtime_linq_edit.json).
- [Normal remote recovery](../tests/graph_build/upstream/runtime_complete_remote.py): `--phase producer --cache-url URL`, stop producer, fresh consumer `--phase consumer --seed-evidence PRODUCER/seed.json` (`--edits --evaluation-reuse` checks retention/failure reset).
- [Project-only HTTP recovery](../tests/graph_build/upstream/runtime_remote.py): fresh consumer/base with both Bazel action caches disabled.
- [Verification probes](../tests/graph_build/package_verification.py) and [replay probes](../tests/graph_build/replay.py): child reads, corruption, and parity.

Drivers accept `--help`. Full historical tables/commands: [versioned record](https://github.com/keegan-caruso/msbuild-bazel/blob/fa2764b55f630ae0462e836aa3163b0807f07f7f/docs/performance.md). See [support](support.md) for limits.

## Sustained catalog application

5-project package-backed catalog app (Razor/API, JSON, deps/analyzer, unit tests, static assets) on Ubuntu 26.04 ARM64, SDK **10.0.400**, Bazel **9.3.2**; guest configured 4 CPUs / 6 GiB (reported 5 online CPUs), 2 Bazel jobs, 1 local test, 1 worker/key (no source-runtime production). Five distinct body edits (reused 4 / compiled 1, ref bytes unchanged), 5 API edits (reused 1 / compiled 4, ref bytes changed), and 5 Publish runs each ran HTTP smoke + forced tests: all **33 commands** (incl. bootstrap/seed) passed, **25 forced tests**:

| Invocation | Observations | p50 | Nearest-rank p95 |
| --- | ---: | ---: | ---: |
| Body edit + app HTTP smoke | 5 | 1.435 s | 1.485 s |
| API edit + app HTTP smoke | 5 | 3.060 s | 3.225 s |
| Publish + app HTTP/static smoke, mixed initial/retained target | 5 | 1.428 s | 8.290 s |

Whole Bazel invocations (not HTTP latency; p95 = max of 5; initial Publish **8.290 s**, retained 4 runs **1.378–1.434 s**; bootstrap **62.03 s**, sync-check **3.94 s**, initial seed **8.85 s** excluded; not paired vs raw). At 0.25 s sampling: min available memory **4,966,104 KiB**, peak summed RSS **1,508,003,840 bytes** (double-counts shared pages), max boundary disk for owned consumer/base **535,314,432 bytes** (+**200,704 bytes** from first to last Publish/test cycle). Keeps 4-CPU / 6-GiB cap (does not set universal budget or close source-producer gate). Reproduce in qualified guest (fresh dir outside checkout; Build/Publish workers, no HTTP project cache):

```sh
python3 benchmarks/sustained.py OUTPUT --revision RULES_COMMIT --samples 5
```
