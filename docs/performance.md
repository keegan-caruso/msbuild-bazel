# Performance versus raw MSBuild

## Sync preparation

Multi-root offline sync calls each root's Restore target within one native
MSBuild invocation. Shared configured dependencies reuse evaluation/target results;
root hooks and per-entry properties remain intact. Single-root Restore is unchanged.
Private qualification uses normal SDK targets; the sections below describe
whole-action and project reuse.

Synthetic roots share a three-library chain: Linux ARM64, four CPUs / 6 GiB,
SDK **10.0.400**, no external packages. Three alternating before/after pairs against
**da16128**, fresh private workspaces, medians in seconds. Each pair verifies
byte-identical generated JSON and Starlark; later samples also run `--check`.

| Roots / projects | Offline sync before → after | With compiler qualification before → after |
| --- | ---: | ---: |
| 1 / 4 | 0.64 → 0.59 | 2.44 → 2.44 |
| 4 / 7 | 2.00 → 0.74 | 5.10 → 3.88 |
| 16 / 19 | 7.66 → 1.24 | 15.67 → 9.36 |
| 64 / 67 | 30.12 → 3.36 | 58.12 → 31.60 |

At 64 roots, offline sync fell **88.8%** and qualified sync **45.6%**.
SDK/runner acquisition, NuGet update and ordinary incremental builds are excluded.
These small compilations isolate repeated Restore work. The
[runtime preparation profile](#runtime-preparation) identifies private Build as
the remaining cold cost.

Build each revision's `tools/ProjectSync/ProjectSync.csproj` with the same pinned SDK,
using `-c Release -o ABSOLUTE_PAYLOAD_DIRECTORY`, then run from this checkout:

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK bash tests/project_sync/preparation_benchmark.sh \
  FRESH_OUTPUT BASELINE/ProjectSync.dll CANDIDATE/ProjectSync.dll
```

Paths should be absolute. Optional trailing root counts select individual sizes.
CSV/logs stay in `FRESH_OUTPUT`; the benchmark does not reuse qualification products.

## Cached preparation

With a complete `msbuild_sync(srcs = ...)` snapshot, Bazel can reuse qualification
between sync and check. Linux ARM64, four CPUs / 8 GiB, SDK **10.0.400**, Bazel
**9.3.0**. The same synthetic three-library chain and unchanged graph declarations
are used by both modes. Three alternating public `bazel run` pairs; median wall
seconds, including publication/check:

| Roots / projects | Ordinary `--check` | Cached `--check` |
| --- | ---: | ---: |
| 1 / 4 | 2.580 | 0.094 |
| 16 / 19 | 9.537 | 0.087 |
| 64 / 67 | 31.887 | 0.094 |

At 67 projects, unchanged checks took **99.7% less time**, with no qualification
action executed. Single cold observations were **34.85 / 34.53 s** for ordinary /
cached sync, including runner bootstrap; both compiled all 67 projects.
These are reuse measurements, not new
large-runtime or incremental-build timings. SDK/registry acquisition is excluded;
the harness separately records cold runs including runner bootstrap. Native cache
controls verify that changed source bytes/membership, definitions, props, mappings,
producer artifacts and package inventories requalify, while unchanged checks do not.

```sh
RULES_MSBUILD_BAZEL=PINNED_BAZEL bash tests/project_sync/cached_preparation_benchmark.sh \
  FRESH_OUTPUT ABSOLUTE_RULES_CHECKOUT
```

Optional trailing root counts select sizes (default **1 / 16 / 64**). Set
`RULES_MSBUILD_TEST_REPOSITORY_CACHE` to an existing verified acquisition cache.
`SYNC_PREPARE_CACHE_URL=URL` seeds a normal Bazel remote cache. Relocate the source
workspace and identical rules, stop the producer, then run `bazel run //:sync
--remote_cache=URL --disk_cache= --lockfile_mode=error -- --check` with a fresh
`--output_base`. The independent four-project control recovered bootstrap and
preparation remotely with zero qualification executions and identical declarations.

### Runtime preparation

Runtime v10.0.0, Linux ARM64, four CPUs / 8 GiB, SDK **10.0.400**, Bazel **9.3.0**.
The declared snapshot includes roughly 61,000 authored files. The full managed
graph (**543 configurations / 481 compilation nodes**) produces byte-identical
JSON and Starlark to retained ordinary sync. One isolated cold diagnostic run
with serial compiler qualification (revision `28b36dc`):

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

The private Build accounts for **96.4%** of the sync process. Totals include
additional inventory, publication and cleanup work; this is a profile, not a paired
cold speedup. Three unchanged checks took **3.34 / 1.98 / 0.47 s**, each with zero
preparation executions. Ordinary incremental-build timings are unchanged by this
qualification measurement.

A 32-configuration Pipelines control matches freshly executed ordinary sync;
body/API, props, mappings and lock-byte edits requalify, unchanged checks reuse,
and original-state remote recovery restores identical declarations. The JIT control
also verifies an actual source-runtime reference DLL change invalidates preparation,
restoring it recovers the prior result, and all six upstream tests execute.

Use the source workspace retained by `runtime_downloaded_prepare.py` or
`runtime_jit_public_prepare.py`, not the pruned build consumer:

```sh
python3 tests/graph_build/upstream/runtime_preparation_cache.py \
  SOURCE_WORKSPACE RESULTS --output-base=FRESH_BASE --cache-url=URL
```

`--controls` exercises Pipelines edits; `--producer-controls=SOURCE_RUNTIME` exercises
the JIT reference producer. For a separate cold profile, use `--profile` and
`--reference-contracts=ORDINARY_DECLARATIONS` to avoid another full ordinary Build.
The helper checks parity, action execution counts and restored output hashes.

With the producer stopped, a relocated four-CPU / 6 GiB consumer, fresh output base,
strict module lock and no disk cache recovered full managed preparation in
**17.78 s**: **144 remote spawn hits / zero executions**, identical declarations.
Runtime-bootstrap recovery took **8.14 s**, with **37 remote spawn hits / zero
executions**. These single observations include consumer startup/acquisition work;
replayed producer profile lines are not consumer execution timings. The final live
runtime/JIT reseed exhausted host storage and is excluded from successful recovery
results; the six-test local qualification and producer-API controls passed.

To repeat independent recovery, relocate the same sources/rules and native locks,
stop the producer, then run the helper with `--consumer --seed-report=PRODUCER_SEED`.
Use `--profile` only when the seed also used it, to preserve the action environment.

### Parallel compiler qualification

Private qualification now allows up to four MSBuild nodes, bounded by available
CPUs. The full SDK Build and input-mutation checks remain. Bazel accounts for four
CPUs / 4 GiB for cached compiler qualification. Linux ARM64, four CPUs / 8 GiB,
SDK **10.0.400**, serial baseline **28b36dc**; alternating pairs, median seconds:

| Scope | Serial command | Parallel command | Serial private Build | Parallel private Build |
| --- | ---: | ---: | ---: | ---: |
| Synthetic, 17 projects, three pairs | 9.06 | 6.80 | 7.89 | 5.75 |
| Runtime Pipelines, 32 configurations, two pairs | 133.30 | 103.49 | 113.26 | 90.78 |

Both declarations match byte-for-byte in every sample. Pipelines command time fell
**22.4%**, private Build **19.9%**. Each invocation has fresh private outputs and
fixed sources, SDK and packages; OS caches are not reset. Acquisition, NuGet update,
Bazel staging and ordinary incremental builds are excluded.

Build both revisions' ProjectSync payloads, then reproduce the synthetic pairs:

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK python3 benchmarks/qualification.py FRESH_OUTPUT \
  --baseline-runner=BASELINE/ProjectSync.dll \
  --candidate-runner=CANDIDATE/ProjectSync.dll
```

For runtime pairs, use each payload with the same owned source workspace and
verified package bindings, with `RULES_MSBUILD_SYNC_PROFILE=1`:

```sh
PINNED_SDK/dotnet PAYLOAD/ProjectSync.dll SOURCE PINNED_SDK/sdk/10.0.400 \
  src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj \
  --framework net10.0 --package-build --resolve-references --mappings mappings.json \
  --inputs INPUTS.json --runfiles RUNFILES
```

A separate full-runtime profile qualified **543 configurations / 481 compilations**
with identical declarations: private Build **1,016.89 s** (**95.9%** of sync), total
**1,059.89 s**. The earlier serial private Build was **1,362.47 s**; these are
separate profiles, not paired scores. The new run invokes ProjectSync directly,
excluding Bazel staging/publication and acquisition. Remote-recovery figures above
predate this concurrency change.

### Project qualification reuse

Opt-in qualification caching reuses individual projects inside a changed sync
preparation action. It does not replace the ordinary graph-build cache. Keys use
conservative dependency inputs; evaluation and contract validation still run.
The original measurements below execute fresh Restore; the preparation-reuse
section measures verified Restore replay. Misses use normal SDK Build. See [configuration](api.md#compiler-selections).

Runtime v10.0.0, **543 configurations / 481 cacheable projects**, SDK **10.0.400**,
Linux ARM64, four CPUs / 8 GiB, qualification core **bc745a1**. Single direct-CLI
diagnostic observations; these are sync preparation, not ordinary build scores:

| Case | Total seconds | Private Build seconds | Project hits | Csc tasks |
| --- | ---: | ---: | ---: | ---: |
| Empty project cache | 1,168.40 | 1,109.78 | 0 | 611 |
| Empty local cache, HTTP recovery | 52.97 | 2.82 | 481 | 0 |
| Pipelines body edit | 60.20 | 22.21 | 474 | 7 |
| Pipelines implementation + reference API edit | 68.27 | 28.62 | 464 | 17 |
| Original sources restored, local reuse | 39.75 | 1.86 | 481 | 0 |

Every row preserves both declarations byte-for-byte against ordinary sync. Body
edits add `GC.KeepAlive` in `PipeOptions`; API edits add a method to implementation
and reference sources. Cache keys remain conservative across dependencies.
An earlier local replay took **88.50 s** with 481 hits / zero Csc tasks; filesystem
cache states differ, so these profiles do not compare local and HTTP transport
speed. Body/API controls resumed after host disk exhaustion; deleted scratch
blocks were released between those measured commands. The interrupted row is excluded.
On original-state replay, Restore (**21.69 s**) and evaluation/input handling now
dominate; the private Build is **1.86 s**. The large HTTP row uses another empty
cache on the same VM; independent-machine correctness is the separate control below.

Correctness controls passed both Bazel pins on Linux ARM64 / SDK **10.0.400**.
A separate producer/consumer control stopped the producer before recovery: a new
local cache on the other VM recovered all four projects in **1.29 s**, with zero
Csc tasks and identical declarations. This is a recovery control, not a paired
speedup; the producer/consumer had four CPUs and 6/8 GiB respectively.

To measure project reuse, repeat the pinned runtime command above with
`--qualification-cache OWNED_CACHE --qualification-cache-url http://cache:8080`.
Use a new empty `OWNED_CACHE` for HTTP recovery. `RULES_MSBUILD_SYNC_PROFILE=1`
reports phases; `PROJECT_SYNC_CACHE` reports project hits/misses and actual Csc
task calls. SDK/acquisition and Bazel staging are outside these direct profiles;
OS caches are not reset. Raw reports stay outside Git.

## Downloaded-SDK workflow

Runtime v10.0.0, four managed roots (Pipelines, Encodings.Web, Json and ComponentModel
Primitives): **182 configurations / 163 compilations**. Linux ARM64, four CPUs,
6 GiB, SDK **10.0.400**, Bazel **9.3.0**, default worker budgets and fresh evaluation.
The public updater generated **106 archives / 91 native locks**; offline sync/check
qualified SDK compiler selections. Unprofiled wall seconds:

| Case | Raw MSBuild | Graph | Graph reused / compiled |
| --- | ---: | ---: | ---: |
| Cold Restore + Build | 371.24 s | 384.49 s | 0 / 163 |
| No-op | 5.94 s | 0.14 s | Whole action hit |
| Pipelines body edit | 18.36 s | 17.55 s | 158 / 5 |
| Pipelines API edit | 32.59 s | 37.93 s | 147 / 16 |

Cold is one observation with fresh outputs/snapshots; tools/packages were available
and graph bootstrap (29.27 s) was separate. Incremental rows are medians of three
alternating pairs, matching all **1,447 DLL/PDB/resource files**. Separate instrumented
controls matched the actual body/API compiler sets (**5 / 16**); they are excluded
from scores. Body/API reused Restore. Three local project recoveries took **5.85–7.53 s** with
163 hits, zero compilations and byte parity. Cold/API overhead was **3.6% / 16.4%**;
this default-contract result does not use the opt-in retention of the larger baseline.

Independent HTTP recovery on a fresh, relocated Linux ARM64 machine, with the
producer stopped: **5.41 s** for cached Restore + graph actions. Forcing graph
execution retained the Restore action hit and recovered **163 project snapshots /
zero compilations** in **16.11 s**. Both matched all **3,980 retained files**, including
modes. Acquisition/bootstrap were separate. A Bazel-tested app imported the graph
from another module, verified the exact source-built Pipelines DLL hash, and used
its `Pipe` API on the downloaded SDK host.

Package update/check each took about **51 s**; offline sync/check's private Build
check took **598 s**. These declaration-update costs are outside build scores.
Reproduce with [preparation](../tests/graph_build/upstream/runtime_downloaded_prepare.py)
(`SOURCE_ARCHIVE OUTPUT`), then [benchmark](../tests/graph_build/upstream/runtime_benchmark.py)
(`OUTPUT/workspace RESULTS --output-base=FRESH_BASE --slice=loaded-common
--samples=3 --memory-gib=6 --cold-build --trim-between-rows`). Use the pinned source
archive hash in the preparation driver. This is a bounded managed slice, not the
entire runtime repo or first-time acquisition.
For recovery, run [complete remote](../tests/graph_build/upstream/runtime_complete_remote.py)
with `--phase=producer --cache-url=URL`; relocate the workspace to another machine,
stop the producer, and run `--phase=consumer --seed-evidence=SEED_JSON`.
Then run [consumer smoke](../tests/graph_build/upstream/runtime_downloaded_smoke.py)
with `RUNTIME_WORKSPACE FRESH_APP --cache-url=URL`.

## Qualification preparation reuse

Linux ARM64, SDK 10.0.400, four CPUs / 8 GiB; a 17-project synthetic with one
consumer and 16 independent producers. Three distinct body edits and three API
edits per runner, unprofiled, warm acquisition/cache; medians:

| Preparation | Body | API |
| --- | ---: | ---: |
| Project qualification cache, fresh Restore | 2.38 s | 2.39 s |
| Verified Restore replay, reviewed edit input | 1.95 s | 1.93 s |
| Full evaluated-state transfer to MSBuild nodes | 1.92 s | 1.93 s |
| Shared immutable hashes + verified copy/clone replay | 1.63 s | 1.63 s |

Full-state transfer alone showed no material small-graph incremental gain.
All versions compiled two projects per edit and emitted identical JSON/Starlark contracts.
Versions ran consecutively, not alternating pairs; these are small-graph diagnostic
comparisons, not updated runtime scores. Restore replay still verifies every file.
Cloning falls back to copies on the qualified ext4 filesystem. SDK bytes are read
once per invocation; package digests share that read-only lifetime. Mutable project
inputs retain fresh pre/post-Build verification.

For alternating pairs on a fresh 17-project fixture, build both payloads and run:

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK python3 benchmarks/qualification.py FRESH_OUTPUT \
  --baseline-runner=BASELINE/ProjectSync.dll \
  --candidate-runner=CANDIDATE/ProjectSync.dll \
  --cached-edits --width=16 --depth=1 --samples=3
```

This excludes initial cache seeding and checks compiler counts and declaration
hashes after every distinct body/API edit. Use `--profile` separately for phases.
A separate four-project Linux ARM64 consumer recovered Restore and all projects in
**1.01 s**, with the producer stopped, no copied local cache, zero compilations
and byte-identical declarations. This single correctness profile excludes acquisition.

## Reviewed evaluation reuse

On the same 163-compilation downloaded-SDK slice, opt into only the two reviewed
Pipelines body/API sources. Three alternating unprofiled pairs per mode, four CPUs,
6 GiB, default 512 MiB evaluation budget, HTTP project caching enabled:

| Edit | Retained graph | Fresh graph | Raw paired with retained |
| --- | ---: | ---: | ---: |
| Body | 16.26 s | 18.84 s | 18.98 s |
| API | 31.06 s | 42.62 s | 35.85 s |

The fresh-control raw medians were 19.47 / 33.46 s. Retention saved **2.58 / 11.55 s**
against fresh graph medians; the retained API median was **13.4% below** its paired
raw median. These are separate HTTP-enabled observations from the default baseline
above. All 1,447 required files matched; edits reused Restore and all 182 evaluations,
while compiling the same 5 / 16 projects. Separate profiled controls verify actual
compiler sets for both modes; their times are excluded from scores.

Separate API profiles put project evaluation at **1.83 → 0.22 s**, input hashing
at **0.92 → 0.45 s** and snapshot replay at **2.05 → 1.37 s**; publication stayed
near **0.06 s**. These overlapping profile totals do not explain the entire wall-
time difference and are not additional paired speedups.

Use `runtime_downloaded_prepare.py SOURCE_ARCHIVE OUTPUT --evaluation-reuse`.
For comparison against a completed scorecard, run `runtime_benchmark.py` with
`--slice=loaded-common --qualified-raw-results=PRIOR_RESULTS --evaluation-reuse
--compare-fresh-evaluation --project-cache-url=URL --memory-gib=6 --samples=3
--diagnostics --trim-between-rows`. Supply a separate workspace containing the
reviewed `EvaluationReuseInputs` and a separate existing output base. The harness
requires identical raw/graph semantics and rejects changed ownership or other inputs.
See [evaluation contracts](api.md#caching-and-workers) before expanding exemptions.

## Large downloaded-SDK graph

The same public SDK → native NuGet update/check → offline sync/check workflow now
covers **39 roots / 543 configurations / 481 compilations**, using **141 package
archives / 265 native locks**. Runtime v10.0.0, Linux ARM64, four CPUs, 8 GiB,
SDK **10.0.400**, Bazel **9.3.0**, HTTP project caching, four MSBuild nodes.
Three alternating unprofiled pairs; medians:

| Case | Raw MSBuild | Graph | Graph reused / compiled |
| --- | ---: | ---: | ---: |
| No-op | 17.89 s | 0.26 s | Whole action hit |
| Pipelines body edit | 31.65 s | 26.49 s | 475 / 6 |
| Pipelines API edit | 46.00 s | 41.39 s | 464 / 17 |

Body/API were **16.3% / 10.0% below** raw, with all **3,622 DLL/PDB/resource
files** matching. Separate instrumented controls matched the actual compiler sets
(**6 / 17**); their times are excluded. Edits reused Restore and all 543 evaluations.
Three local project recoveries took **17.69–19.89 s**, with 481 hits / zero compilations.

Retention needs an explicit **1024 MiB evaluation budget** for this graph. A separate
profile measured **676.7 MiB managed memory**; the default 512 MiB budget correctly
retired evaluations. The general default remains unchanged. Single cold Restore +
Build: **1086.80 s** (Restore **84.88 s**, graph **990.34 s**), excluding bootstrap.
There is no new paired cold result; full-source raw correctness ran during unscored
preparation. This contract retains disposable intermediates, so its file counts and
Pipelines edits differ from the older LINQ baseline below.

Earlier source-only package update/check measured **147.19 / 175.91 s** and ordinary
compiler-selection sync/check **1526.98 / 1469.58 s** (unpaired). The
[current preparation profile](#runtime-preparation) measures declared-source reuse;
these preparation costs are outside incremental-build scores.

A fresh relocated Linux ARM64 consumer, four CPUs / 6 GiB, with the producer stopped,
recovered normal Restore + graph actions in **8.83 s**. Forced graph execution took
**30.28 s**, retained the Restore remote hit and recovered **481 HTTP project
snapshots / zero compilations**. Both matched **10,780 retained files**, including
modes. These separate recovery controls used the producer's default 512 MiB budget;
acquisition/bootstrap were separate.

The current-code correctness refresh seeded **481 compilations** on a healthy
four-CPU / 8 GiB producer, then stopped it. An independent four-CPU / 6 GiB consumer
actually executed the app and all eight suites after normal Restore/graph remote
action hits, then after forced **481 HTTP project hits / zero compilations**.
Both runs matched all **10,780 files**, normalized **118,952 passed / 64 skipped**
cases and **96 loaded-runtime observations**. Test-result caching was disabled.
The refresh also matches the earlier producer's entire retained byte/mode inventory.
These are full-workflow correctness controls, not new paired build timings.

Prepare with `runtime_downloaded_prepare.py SOURCE_ARCHIVE OUTPUT
--slice=runtime-suites --evaluation-reuse --evaluation-cache-mb=1024`, then use
`runtime_full_source.py` for locked full-source raw qualification and
`runtime_benchmark.py --slice=runtime-suites --qualified-raw-results=RAW_RESULTS
--evaluation-reuse --samples=3 --memory-gib=8 --project-cache-url=URL --diagnostics
--trim-between-rows`. For independent recovery use `runtime_complete_remote.py`
with the same source/contract and budget on producer and consumer. For actual suite
execution use `runtime_recovered_tests.py WORKSPACE RESULTS --phase=producer
--output-base=FRESH_BASE --cache-url=URL --host-space-path=HOST_BIND`. Relocate the
source-only fixture, stop the producer, then use `--phase=consumer` and
`--seed-report=PRODUCER_RESULTS/seed.json` with another fresh base. Public preparation
performs full SDK compiler qualification; it is outside incremental scores.
See [runtime support](support.md#downloaded-sdk-and-runtime-sources) for scope.

## Paired runtime baseline

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`): **260 project paths /
543 configurations / 481 compilations / 39 roots**. Linux ARM64, four CPUs, 8 GiB,
SDK 10.0.400, Bazel 9.2.0, four MSBuild nodes, one worker. Complete compiler
inventories at **b3cf505**, 8192 MiB project cache and 1024 MiB evaluation budget.
The production defaults are smaller; see [worker settings](api.md#caching-and-workers).

Three alternating raw/graph pairs, unprofiled; median wall seconds:

| Case | Raw MSBuild | Graph | Reused / compiled projects |
| --- | ---: | ---: | --- |
| No-op | 17.63 s | 0.29 s | Whole Bazel action hit |
| LINQ body edit | 22.24 s | 18.11 s | 480 / 1 |
| LINQ API edit | 154.84 s | 129.83 s | 434 / 47 |

Body/API medians were **19% / 16% lower** than raw. Both sides compiled the same
project sets and matched all **2,814 required DLL/PDB/resource files**. Edits reused
all 543 evaluations and prepared Restore. Three local recoveries had 481 hits,
zero compilations and took 18.44–20.84 s. Graph files publish read-only; raw parity
compares bytes, not identical raw file modes.

These observations apply to this graph and reviewed contracts, not every project.
Acquisition, seeding, priming, comparison and trimming were unscored. Failed harness/
disk attempts are excluded. Profiling ran separately; scopes may overlap.

Earlier paired cold Restore + Build at **8d83f0f**: graph **1061.33 s**, raw
**1056.91 s** (0.4% overhead), matching all 3,622 then-published products.
SDK/packages and Bazel bootstrap were available; outputs/snapshots were fresh.
This is cold compilation, not first-time acquisition, and predates the latest contracts.
There is no new paired cold result for complete compiler inventories.

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

Combined fingerprints stream JSON into `IncrementalHash` rather than allocating
its full string/UTF-8 array. Prior-key compatibility and corruption controls passed;
no material verification-time gain was measured. Read-only binds, timestamps and
inode identity never replace per-request byte verification.

Generic sync at **4bc0cd2** reproduced all 2,970 reviewed project compiler selections.
One unprofiled validation pair compiled 1/47 projects, matched 2,814 required files,
and recovered all 481 snapshots. It extends correctness coverage, not the paired
baseline above; private sync qualification performs a full Build.

## Complete remote-cache recovery

At **bee52f6**, a fresh relocated Linux ARM64 consumer with the producer stopped,
fresh output bases, normal Bazel HTTP caching and no local disk cache recovered
the same 481-compilation graph. One unprofiled observation per case:

| Case | Wall time | Restore | Graph |
| --- | ---: | --- | --- |
| Whole-action recovery | 8.32 s | Remote hit | Remote hit |
| Forced graph execution | 28.99 s | Remote hit | 481 project hits / zero compilations |
| Pipelines body edit | 26.64 s | Reused | 475 hits / six compilations |
| Pipelines API edit | 39.82 s | Reused | 464 hits / 17 compilations |
| Compiler failure recovery | 31.02 s | Reused | 475 hits / six compilations |

All 9,972 retained files matched seed bytes/modes; every snapshot payload, including
omissions, remained verified. Edits reused 543 evaluations; compiler failure reset
them. Whole-action reports contain cached producer metadata: spawn logs establish
actual recovery. The earlier 95.65 s Restore result disabled Bazel's action cache
and does not describe this workflow. Recovery is not remote execution.

With complete compiler inventories, a separate stopped-producer consumer with
both Bazel action caches disabled had **481 HTTP hits / zero compilations** and
matched all 9,972 retained files. Acquisition/bootstrap/Restore/build took 124.17 s;
the profiled runner took 17.06 s. This is a correctness control, not a paired
speedup or a new runtime test-suite run.

## Reproduce

For separate sync diagnostics, use `bazel run //:sync
--action_env=RULES_MSBUILD_SYNC_PROFILE=1` with declared `srcs`. Profiling is off
by default. `PROJECT_SYNC_PROFILE` lines report staging, bindings, offline
preparation/Restore, evaluation and private Build; nested totals overlap.
Check the execution log: a remote hit can replay the producer's timing lines.

Use matching source, properties, compiler sets, packages, Restore/cache state,
native products and resource inputs. Keep profiling off for scores. Report project
hits/misses, compiler calls, output byte parity and whether acquisition was timed.
Keep reports outside Git; use `--trim-between-rows` for unscored thin-disk reclamation.

- [Preparation](../tests/graph_build/upstream/runtime_prepare.py):
  `python3 tests/graph_build/upstream/runtime_prepare.py SOURCE FEED WORKSPACE
  --slice runtime-suites --prepared-restore --resolve-references`.
- [Paired edits](../tests/graph_build/upstream/runtime_benchmark.py): use
  a matching `--qualified-raw-results RAW_RESULTS`, reviewed `--reference-bindings
  BINDINGS`, `--samples 3 --evaluation-reuse --replay-omissions`, the
  [six-file evaluation inventory](../tests/graph_build/upstream/runtime_evaluation_inputs.json)
  and [LINQ edit case](../tests/graph_build/upstream/runtime_linq_edit.json).
  [binding preparation](../tests/graph_build/upstream/runtime_reference_bindings.py)
  takes the raw compiler inventory. Generic capture is newer; the baseline used
  explicit reviewed bindings. Restore, reuse and omission contracts must match.
- [Normal remote recovery](../tests/graph_build/upstream/runtime_complete_remote.py):
  `--phase producer --cache-url URL`, then stop the producer and use a fresh
  consumer with `--phase consumer --seed-evidence PRODUCER/seed.json`.
  `--edits --evaluation-reuse` checks retention and failure reset.
- [Project-only HTTP recovery](../tests/graph_build/upstream/runtime_remote.py):
  use a fresh consumer/output base with both Bazel action caches disabled.
- [Verification probes](../tests/graph_build/package_verification.py) isolate child
  reads; [replay probes](../tests/graph_build/replay.py) cover corruption and parity.

Drivers accept `--help`. The complete tables, profiles and historical commands are
preserved in the [versioned record](https://github.com/keegan-caruso/msbuild-bazel/blob/fa2764b55f630ae0462e836aa3163b0807f07f7f/docs/performance.md).
See [support](support.md) for qualification and isolation limits.
