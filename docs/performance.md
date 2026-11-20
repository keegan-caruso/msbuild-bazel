# Performance versus raw MSBuild

## Pinned source lifecycle control

A native macOS ARM64 control on Bazel **9.3.2** installed two synthetic Git
snapshots of the tracked rules source, upgraded from A to B, then rolled back to
A. Each phase used a fresh output base and one shared local action cache. A
consumer analyzed the public `msbuild_graph` rule with a fake SDK and built a
small action using a marker from the selected source. Output bytes were A, B,
A; the action missed on install and upgrade and hit on rollback. This tests that
specific declared action boundary, not .NET compilation, graph recovery or
cross-revision project-cache compatibility. No release was created.

Reproduce with a pinned Bazel executable and new disposable directories:

```sh
python3 tests/tooling/source_distribution_lifecycle.py /tmp/source-lifecycle-run \
  --bazel /absolute/path/to/bazel --disk-cache /tmp/source-lifecycle-cache
```

The driver writes the synthetic commit IDs, consumer module files, action logs
and results in the evidence directory. It shuts down each owned Bazel server.
See [pinning and rollback](api.md#pin-update-and-roll-back-the-rules) for the
consumer policy.

## CI comparison controls

`runtime_recovered_tests.py --demo --test-cache=yes` measures normal CI test-result
reuse; `--require-test-recovery` requires nine remote test hits. Use
`--initial-edit=body|api --edit-token=TOKEN` to edit before a fresh worker's first
build. The default test-cache policy remains `no` for actual-execution controls.
The helper checks HTTP cache reachability before building, so a disconnected cache
cannot silently turn a recovery measurement into a local rebuild.

Prepare raw inputs with `runtime_full_source.py --prepare-only`, then use
`runtime_ci_raw.py --case=body|api --edit-token=TOKEN`. Its first scored run can
also serve as the full-source correctness control.
`--fresh-outputs` removes owned outputs and every declared Restore file,
retaining SDK/packages. Native binaries and unchanged demo helpers are shared
prepared prerequisites. Compare reports with `runtime_ci_compare.py --case=CASE`;
it requires matching contracts, edits, compiled bytes and test outcomes. Managed
output modes follow each producer's policy: raw SDK `0644`/`0744`, Bazel `0555`.
Graph producer/consumer recovery still requires exact file-mode parity.
Report executed tests and remote test hits separately. CI demos default to
top-level downloads, including actual-test and edit controls; complete artifact
verification follows outside the CI timer.
See [measured CI results](#runtime-ci-demo).

For a pruned source handoff, `runtime_full_source.py --bootstrap-unused-locks`
can reconstruct inventory locks outside the declared graph using offline packages.
It requires every declared lock and verifies all retained locks stay identical.
The current runtime control reconstructed five locks while preserving 260; this
is unscored package preparation, not additional build qualification.

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
replayed producer profile lines are not consumer execution timings.

The latest live runtime/JIT handoff recovered preparation in **58.13 s** with
**227 remote spawn hits / zero executions**; an unchanged check took **2.04 s**.
These single observations include first-base startup and repository acquisition
on a separate four-CPU / 6 GiB Linux ARM64 consumer (SDK 10.0.400, Bazel 9.3.0).
All five native producers and managed graphs recovered remotely, then six JIT tests
executed. A forced project recovery reused nine project snapshots with zero
compilations and executed the six tests again. Source/runtime/reference bytes and
modes matched the producer and retained raw-qualified control. This is a recovery
qualification, not a paired raw-MSBuild timing comparison.

To repeat independent recovery, relocate the same sources/rules and native locks,
stop the producer, then run the helper with `--consumer --seed-report=PRODUCER_SEED`.
Use `--profile` only when the seed also used it, to preserve the action environment.
For JIT, close inputs with `runtime_jit_public_consumer.py PREPARED SEED OUTPUT
--preparation-base=BASE`; this retains the declared sync snapshot and module locks.

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

`qualification_cache = True` adds verified Restore and project snapshots inside a
changed preparation action. Misses execute normal SDK targets; post-Restore graph
evaluation and contract validation remain fresh. Keys retain conservative dependency
inputs. See [configuration](api.md#compiler-selections).

#### Qualification-to-Build handoff

`seed_build_cache = True` reuses qualification's compiled products in ordinary
Build snapshots. The complete managed runtime graph at `60629d1` (631 configurations)
passed on Ubuntu 22.04 ARM64, four CPUs / 8 GiB RAM plus 4 GiB swap, SDK **10.0.400**
and Bazel **9.3.0**. Cold qualification ran **691 Csc tasks** and seeded **563**
assembly snapshots; seed verification/publication took **41.11 s**. Both ordinary
Builds below recovered all 563 snapshots with zero misses. The first consumer's
keys and manifest bytes matched the seed; a separate binlog control recorded
**zero Csc/Vbc calls**.

| Consumer state | Bazel wall | Restore action | Graph action | Graph runner |
| --- | ---: | ---: | ---: | ---: |
| New Restore contract | 447.84 s | 408.72 s | 36.07 s | 21.49 s |
| Restore prepared | 40.84 s | Action hit | 35.68 s | 20.91 s |

Tools/packages were available; Bazel disk/remote caches were disabled, while the
local action cache retained Restore.
The second request changed only the cache URL's trailing slash to force graph
execution while retaining Restore. Action durations come from Bazel's native
trace; the runner is inside the graph action. These are single correctness
observations, not paired speedups. Qualification still performs the initial SDK
Build; the handoff removes its repetition. It also declares 63 formerly omitted
file members of reviewed evaluation items in Build and Restore.

Enable the flag on the retained runtime workspace's `//:sync` and use the same
HTTP project cache with `app_graph(linux_stable_paths = True)`. The smaller,
independently runnable [controls](support.md#project-qualification-cache) cover
both Bazel pins, output parity, relocation and body/API invalidation.

#### Small graph

Linux ARM64, SDK **10.0.400**, four CPUs / 6 GiB; 17 projects, one consumer and
16 producers. Three alternating unprofiled pairs with distinct body/API edits;
cache seeding excluded. Baseline **d1021ba**, candidate **59d3a79**; medians:

| Edit | Fresh Restore | Restore reuse + shared hashing/materialization |
| --- | ---: | ---: |
| Body | 2.42 s | 1.65 s |
| API | 2.39 s | 1.65 s |

Every row compiles the same two projects and produces identical declarations.
[Intermediate diagnostics](https://github.com/keegan-caruso/msbuild-bazel/blob/7eecc63/docs/performance.md#qualification-preparation-reuse)
separated Restore reuse from shared immutable hashes/verified replay. Full evaluated-
state transfer alone showed no material small-graph incremental gain. Cloning falls
back to ordinary copies on the qualified ext4 filesystem.

```sh
RULES_MSBUILD_DOTNET_ROOT=PINNED_SDK python3 benchmarks/qualification.py FRESH_OUTPUT \
  --baseline-runner=BASELINE/ProjectSync.dll \
  --candidate-runner=CANDIDATE/ProjectSync.dll \
  --cached-edits --width=16 --depth=1 --samples=3
```

Use `--profile` separately for phase diagnostics. The helper checks compiler counts,
declaration hashes and source restoration.

#### Runtime graph

Runtime v10.0.0, **543 configurations / 481 cacheable projects**, SDK **10.0.400**,
Linux ARM64, four CPUs / 8 GiB, code **59d3a79**. Single direct-CLI profiles on one
VM; each HTTP row starts with an empty local cache. These measure preparation,
not ordinary builds or paired speedups:

| Case | Total | Restore replay | Private SDK Build | Csc tasks |
| --- | ---: | ---: | ---: | ---: |
| HTTP recovery | 29.99 s | 6.35 s | 3.57 s | 0 |
| HTTP + Pipelines body edit | 47.21 s | 6.66 s | 19.70 s | 7 |
| HTTP + implementation/reference API edit | 59.27 s | 7.47 s | 29.22 s | 17 |

All rows hit Restore and reproduce ordinary sync's JSON/Starlark byte-for-byte.
Body edits add `GC.KeepAlive` in `PipeOptions`; API edits add a method in its
implementation and reference sources. Graph evaluation remains **5.65–6.19 s**;
source copying **2.70–6.44 s**. SDK identity is hashed once per invocation; declared
mutable inputs retain fresh pre/post-Build byte checks.

The empty-cache seed took **1,178.71 s**, including **611 Csc tasks** and cache
publication. It overlapped validation on another VM and is not a paired cold score.
Local replay took **31.76 s**, later original-state recovery **23.08 s**, both with
481 hits / zero Csc tasks. Filesystem cache states differ; do not infer transport
speed from local/HTTP wall times. SDK/package acquisition and Bazel staging are
excluded; scratch blocks were trimmed between commands, outside timers.
[Earlier fresh-Restore profiles](https://github.com/keegan-caruso/msbuild-bazel/blob/d1021ba/docs/performance.md#project-qualification-reuse)
retain the preceding baseline.

For direct reproduction, use the source workspace retained by
`runtime_downloaded_prepare.py --slice=runtime-suites`, its native input manifest
and extracted runfiles, and all 39 `entries` from its BUILD file. This is a harness
handoff. Extend the pinned ProjectSync command above with `--qualification-cache
OWNED_CACHE --qualification-cache-url http://cache:8080`; root `restoreReuseInputs`
reviews the two Pipelines files. Use a fresh cache per HTTP edit and a distinct edit
per compilation control. `RULES_MSBUILD_SYNC_PROFILE=1` reports phases;
`PROJECT_SYNC_CACHE` reports hits/misses and Csc calls. Raw reports stay outside Git.

A separate four-project consumer, including a declared package SDK, recovered
Restore and all projects in **1.14 s** with its producer stopped and no copied local
cache. Zero compilations, identical declarations and all artifact digests matched.
This independent correctness profile excludes acquisition; RBE remains unqualified.

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

## Source SDK production and recovery

One native Ubuntu 26.04 ARM64 / LLVM 18.1.8 trial on Bazel **9.3.2** rebuilt VMR
`b0f34d51fccc69fd334253924abd8d6853fad7aa` using
[rules `4158b03`](https://github.com/keegan-caruso/msbuild-bazel/tree/4158b034e2917990287753f5b2805b6f47b27318).
Controller SDK **10.0.400**, upstream SDK **10.0.100-rc.2.25502.107** and verified
source-built bootstrap artifacts remain separate declared inputs. The
`Private.SourceBuilt.Artifacts.Bootstrap.tar.gz` input has SHA-256
`47f6aea3a4688d24bcb5aee0b8b394398ae8bd7244c8ccabe938bb5dd2a19487`;
the generated declared `bootstrap.tar` containing it and the upstream SDK has
SHA-256 `974ca15d1498735faa9ef3fa72d85898358bbded97e68b87d1c5aa142c7078a1`. The native
archive SHA-256 `1854d067717cba3afe85c01e166e2a2c7d95c4dafea89e172b69da8b536c874a`
matched the sealed-root preflight; actual upstream C/C++/ASM logs selected Clang
18.1.8. Four CPUs / 8 GiB were configured, with one Bazel job,
`DOTNET_PROCESSOR_COUNT=2` and upstream `BuildInParallel=false`.

| Phase | Wall time | Observed result |
| --- | ---: | --- |
| Upstream source build | 28 min 22.23 s | Actual `SourceSdkBuild` cache miss, SDK 10.0.100 / runtime 10.0.0 |
| Producer Bazel test, including source build | 1,826.669 s | Build and actual smoke test pass |
| Fresh read-only consumer after seed stopped | 727.782 s | All 12 recorded spawns remote hits, including producer and graph |
| Consumer body / API edits | 15.694 / 17.172 s | Graph and tests execute; SDK reused |
| Extra forced smoke test | 12.625 s | Test executes; source SDK does not rebuild |

The upstream time is nested inside the producer Bazel time. The complete guardian
including preparation, export and startup took 2,735.352 s. The new archive is
569,564,274 bytes, SHA-256
`e043c131f157a4dfd8f66bfe6016b95ee301d0265b075a69b5c84dd9577c45a2`.
The fresh consumer copied declared inputs only; its expected archive oracle was
excluded from the consumer workspace. Recovery verified the downloaded archive
against that hash. Both seed and consumer used project-cache read-only mode;
only the seed uploaded Bazel actions. The separate fixture HTTP cache recorded
7,431 successful seed PUTs, **14,987 successful consumer GETs / zero consumer
PUTs**, and unchanged **2,641,967,172** stored bytes. Its 6 GiB disk / 2 GiB request
limits and single connection deliberately bounded transfer concurrency; recovery
includes serial SDK-tree downloads. There is no comparison with older timings.

Across 1,911 producer samples, minimum available guest memory was 1,996,292 KiB,
peak summed RSS was 6,219,744 KiB and maximum whole-guest filesystem usage was
34,674,176,000 bytes. Summed RSS can count shared pages repeatedly. GNU time's
separate maximum-resident-set measure was 2,334,916 KiB. One cold producer and
one recovery are not sustained or paired measurements.

A cold consumer with the
[SDK 11 rules candidate `6760e9f`](https://github.com/keegan-caruso/msbuild-bazel/tree/6760e9f637e257b2c2d070c908dbbd24900a3a5a)
and this new archive alone
also executed package and Razor tests and ran the published app. Its controller
used SDK 11.0.100; the declared source SDK remained 10.0.100 / runtime 10.0.0.
The generated package identified `SourceSdk.Package` 1.0.0 with
`lib/net10.0/Package.dll`, SHA-256
`3fa898a68359711ef6f576b044dde2feb0a840678bfdb4eb899fc92bfd24bb10`.
No old component-bundle overlay or source rebuild occurred in that handoff.
Guest-local outputs and non-overlapping host mounts were used. See the
[qualified scope](support.md#source-toolchains-and-nativeaot) for platform limits.
Use the [producer](../tests/source_sdk/source_action_prepare.py) with verified
VMR/bootstrap inputs, then the [recovery driver](../tests/source_sdk/source_action_recovery.py)
and [consumer scenarios](../tests/source_sdk/consumer_scenarios.py).

## Fresh .NET 11 VMR smoke-test recovery

The [Linux ARM64 VMR recipe](../tests/source_sdk/LINUX_ARM64_11.md#recover-the-sdk-and-exercise-consumers)
supports Bazel's top-level output download mode. It lets a fresh consumer run
`//:smoke` while the complete SDK archive and intermediate compiler layouts
stay in the HTTP cache.

The comparison used Bazel 9.3.2, Ubuntu 26.04 ARM64, four CPUs, 6 GiB RAM and
the same source-produced SDK 11.0.100 / runtime 11.0.0 seed. The producer had
stopped. Both modes used one remote connection, disabled cache uploads and disk
caching, and forced the local test to execute. Each invocation used fresh
workspace, output base and output user root directories in one guest. Times
measure the Bazel invocation; guest preparation and seed extraction preceded
the trials.

| Pair | All outputs | Top-level outputs | Speedup |
| --- | ---: | ---: | ---: |
| 1 | 905.8 s | 74.7 s | 12.1× |
| 2 | 945.1 s | 71.9 s | 13.1× |
| 3 | 901.1 s | 71.6 s | 12.6× |

Median paired speedup was **12.6×**. All six runs executed the smoke test on
runtime 11.0.0 and recovered the same SDK digest. Only the full-download runs
materialized the SDK archive. Trial order was top-level/all, all/top-level,
then top-level/all. These timings cover fresh smoke tests against a populated
cache on this hardware. SDK production and builds requiring local compilation
have different input requirements.

In the first top-level run, the test's runfiles contained two copies of the
shared frameworks at different paths: the launch helper's runtime and the
application's selected runtime. All 333 relative file paths and digests matched.
Core accounted for 184.0 MiB and ASP.NET Core for 25.7 MiB per layout. These
are uncompressed file sizes. The test process itself took 76 ms. Bazel's
profiles for the second and third top-level runs attributed 48.93 and 48.32
seconds to staging remote inputs for the test, starting about 21 seconds
into each Bazel invocation. The profiles do not measure wire bytes per layout.

To reproduce a pair, set `seed` and `cache` to the prepared seed workspace and
its populated HTTP cache. Set `RULES_MSBUILD_BAZEL` to the repository's Bazel
launcher. Use a new `trial` directory for each pair:

```bash
for mode in all toplevel; do
  python3 "$rules/tests/source_sdk/source_action_recovery.py" \
    "$seed" "$trial/$mode" --cache="$cache" --smoke-only \
    --download-outputs="$mode" --remote-connections=1
done
```

## Retained source SDK consumer recovery

On Ubuntu 26.04 ARM64 with Bazel **9.3.2**, a retained source-built SDK archive
(SDK 10.0.100 / runtime 10.0.0, SHA-256
`dc795ffff8b6b3c2adac341c844ca71116cb2144c4c745ee2bc9f52a60836345`)
was declared with `msbuild_sdk`. A cold consumer packed a generated NuGet package,
executed its consumer and Razor tests, then published and ran an app. The archive
came from the historical Ubuntu 22.04 source build; no SDK source producer ran
in this control.

A seed guest uploaded the consumer actions, then stopped. A fresh guest with an
empty output base, uploads disabled and project cache read-only recovered the
SDK layout, Pack, package extraction, graph and Publish layout actions over HTTP.
Both tests were forced to execute. Package SHA-256
`b7a4cd4fccea6be8522d63b6e97bbaa9d7d02068293004fb1a50b05e2d498773` and
four published-file hashes matched; package inspection confirmed its identity,
version and library DLL. Both guests used four CPUs / 6 GiB, two Bazel jobs,
one local test, `--remote_max_connections=8` and the same project-cache URL and
read-only action environment. A prior seed without the intended connection cap
failed with TLS handshake timeouts; the bounded retry passed. Cache size did not
change during the consumer, but request-level PUTs were not measured.

The [consumer driver](../tests/source_sdk/consumer_scenarios.py) ran against a
prepared workspace containing the verified archive, a declared SDK layout and
the source toolchain. Cold correctness used a fresh local output base; recovery
used explicit remote cache flags and forced test execution. This is one same-host
consumer recovery control, not source-producer recovery, a cross-host result,
SDK 11 qualification or a performance benchmark. Guest-local workspace and output
storage were required for the archive's internal symlinks in this Apple Container
setup; an earlier host-mounted output base failed during extraction.

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

### Runtime CI demo

The recorded measurements here use the earlier Ubuntu 22.04 / Clang 14 producer.
Current setup commands below select Ubuntu 26.04 / Clang 18.1.8; these historical
timings are not measurements of the replacement toolchain.

Runtime v10.0.0 (`60629d1`), SDK **10.0.400**, Bazel **9.3.0**, runner SHA
`95368b8b…`. Linux ARM64, four CPUs / 6 GiB per worker; private HTTP cache,
producer stopped, relocated source-only consumer and fresh output bases.
Scope: **39 managed roots / 543 configurations / 481 compilations**, source-native
binaries, SDK/packages and unchanged app/test helpers prepared. Version inputs stay
fixed through the edits. This is a bounded runtime slice, not upstream's full CI.

| Unchanged job | Restore/build | Tests/results | Total CLI |
| --- | ---: | ---: | ---: |
| Raw MSBuild, fresh outputs | 1,030.76 s | 90.37 s, nine actual targets | 1,121.13 s |
| Bazel, download all | 32.01 s | 1.20 s, nine remote test hits | 33.21 s |
| Bazel, top-level downloads | 19.42 s | 1.01 s, nine remote test hits | 20.43 s |
| Bazel, top-level + batched layouts | 13.15 s | 0.99 s, nine remote test hits | 14.15 s |

Raw is one observation. The first two Bazel rows are medians of three alternating
pairs (ABBAAB); the batched row is the median of three further fresh-base runs.
Times exclude interphase report checks. Every Bazel run recovered all build actions
with zero executions, including Restore and five native producers: **309 spawns**
before batching, **186** afterward. Top-level downloads alone reduce CLI time
**38.5%**. A separate diagnostic reduced aggregate
remote-output download spans **8.83 → 0.70 s**; spans overlap and are not wall time.
The top-level proof subsequently downloads all artifacts for auditing, adding
**21.16–21.52 s** before batching or **13.94–14.38 s** afterward outside the CI
timer. Normal CI does not need that audit download.

`msbuild_graph_layouts` replaces **124** host project-directory exports with one
manifest-driven action. The complete host matches **490 legacy files and modes**.

With runner **`039b9ced…`** (parallel staging), three alternating fresh-worker
body-build pairs measured:

| Download policy | Median build CLI | Range |
| --- | ---: | ---: |
| All outputs | 62.11 s | 61.63–63.49 s |
| Top-level outputs | 56.61 s | 56.31–57.18 s |

This removes **5.49 s / 8.8%** by leaving unused expanded NuGet trees remote.
The graph consumes package archives and prepared Restore data. Pins, scope and
consumer resources match the demo above; the stopped producer used 8 GiB to seed
the current runner. Each sample used a fresh base and unique body edit, retaining
**475 hits / six compilations**, reference bytes and all **10,780 file modes**.
Tests and artifact audits are excluded; JSON execution logging and build profiling
are disabled in these scores. A separate JSON control took **57.86 s** and established
zero Restore/native executions; every scored run matched its worker/local action
counts. The demo uses top-level downloads by default; its audit selects the graph,
native products and `runner` output group explicitly.

The revised demo passed independent whole-action recovery and a body edit with
**nine actual test targets / 118,952 passed / 64 skipped**, plus original-output
restoration. The body control matched the archived raw control's **3,622 compiled
files** for the same edit; raw timing was not refreshed. Its JSON-instrumented
build took **60.71 s**, with tests timed separately at **91.66 s**. The targeted
audit added **2.12 s** for whole recovery or **0.56 s** after the local body build;
full byte/mode/runtime verification remained outside those audit-download times.

Earlier single edit observations (runner `95368b8b…`) compare **raw retained
outputs** with a **fresh Bazel worker**, keeping the source changes identical:

| Edit | Raw build/publication | Bazel build | Actual tests, raw / Bazel |
| --- | ---: | ---: | ---: |
| Pipelines body | 29.88 s | 67.29 s | 89.47 / 92.75 s |
| Pipelines API | 45.20 s | 76.86 s | 93.67 / 89.11 s |

Bazel reused **475 / 464** projects and compiled **6 / 17**, with no Restore
execution. Both edits executed all nine test targets and matched raw's **3,622
DLL/PDB/resource files**, normalized cases and **118,952 passed / 64 skipped**
outcomes. Body edits preserve reference bytes. All graph recoveries also match
**10,780 retained files/modes**. The fresh-worker edit overhead remains significant;
these rows are not the retained-worker measurements above.

An updated, separate body-edit profile kept **475 hits / six compilations** and
zero Restore/native executions. Worker wall time was **39.06 s**: staging
**6.00 s**, child **32.52 s**, verification/publication/cleanup **0.54 s**. The
child included **7.32 s** evaluation, **3.30 s** prepared Restore validation and
**18.64 s** execution/recovery. These are diagnostic phases, not a new paired
build score; operation totals can overlap.

The broker now stages independent files with at most four concurrent copies.
Three alternating isolated pairs audited **19,319 files / 2.21 GB** after each
copy. With guest page caches dropped before every sample, staging medians were
**5.82 → 3.89 s** (**33.1% less**). Without explicit page-cache drops, medians
were **1.69 → 1.36 s**.
The child was replaced by a complete byte/mode audit, outside the staging timer.
Full child verification remains required in production. These measurements do
not establish a new end-to-end body/API time or change evaluation costs.

Reproduce staging in a disposable Linux VM using retained, fully materialized
graph inputs and their action request; both runners need their complete payloads:

```sh
python3 tests/graph_build/worker_staging.py /tmp/new-staging-results \
  --execroot=EXECROOT --request=GRAPH_REQUEST_JSON \
  --runner=BASELINE/GraphBuild.dll --runner=CANDIDATE/GraphBuild.dll --cold
```

Normal test-result recovery needs a producer pass with
`runtime_recovered_tests.py --phase=producer --test-cache=yes` before stopping it.
New setups below seed cached tests and default to the cached-CI mode. The runner
requires all nine results to come from the remote cache and prints executed,
remote and local counts. Use `--test-cache=no` to force actual execution.

Set up on an Apple silicon Mac with Git, Python 3 and Apple Container running.
Cold setup requires **60 GiB free** and network access:

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

Current setup builds an Ubuntu 26.04 / Clang 18.1.8 image, records its immutable digest/package
inventory, downloads verified runtime sources and pinned tools, updates NuGet and
qualifies the 39-root graph. It declares five native producers, composes the
source runtime/app and eight suites, then seeds build outputs and test results.
It transfers a manifest-verified input checkpoint, stops the producer and creates
an independent consumer. Consumer setup acquires SDK/package archives and the
runner without building Restore or the managed/native graph; its disposable base
is removed before the timed demo. The default cache is private to the VMs; its
stable alias survives container IP changes.

`setup.json`, frozen rules, input checkpoint, seed, package inventories and logs
stay in the setup directory. Resume uses that snapshot; source/tool changes need
a fresh directory. `--archive-producer` verifies the retained rules, checkpoint and
seed before deleting the stopped VM. Runs require that producer to be stopped or
its archive proof to match the retained files. They use fresh Bazel bases. Existing
saved setups keep their original policy; a setup seeded with `--test-cache=no`
needs a fresh setup to demonstrate remote test-result recovery. Successful runs
restore edited sources/products and remove their output base; failed runs keep
outputs. No GitHub CI is started.

Optional `--image=IMAGE@sha256:DIGEST` reuses an immutable Ubuntu image;
`--cache-url=URL` uses an existing unauthenticated cache. A prior source-only
checkpoint can be supplied with `--prepared-inputs=FILE --prepared-sha256=HASH`;
with an external cache, this path requires **32 GiB free**. Checkpoints contain
source, declarations and pinned archives, not producer outputs or local caches.
They can be exported from a qualified workspace with
`runtime_demo_prepare.py pack --workspace=WORKSPACE --archive=INPUTS.tar.gz`.

Clean setup passed on Linux ARM64 with a freshly built image, downloaded sources
and empty private cache, without a prepared checkpoint. A deliberate interruption
after tools resumed successfully. After verified producer deletion, the consumer
recovered **309 remote build spawns / zero executions** in **28.93 s**, then actually
ran all nine targets in **91.55 s**: **118,952 passed / 64 skipped**, matching
**10,780 files and modes**. The command took **122.37 s**, including interphase
checks; post-run verification took **1.09 s**. These are single observations,
not a paired MSBuild comparison. Cold setup is outside demo timings.

All 20 tooling controls passed in the new image, including archive integrity and
producer-retirement guards. Standalone resume after deletion passed; a changed
retained seed was rejected before execution. The earlier checkpoint setup remains
qualified. Keep the setup directory in durable storage for resume and runs.

## Compilation model comparison

The graph/plugin workflow remains the only compilation backend. A retired native-
batch experiment put the entire Pipelines closure in one action; edits rebuilt
unchanged projects instead of reusing them through the plugin.

Runtime v10.0.0 (`60629d1`), **28 project paths / 42 configurations / 38 compilation
nodes**, SDK **10.0.400**, Bazel **9.3.0**, native Linux ARM64, four CPUs / 6 GiB.
Single unprofiled CLI observations in seconds, with identical configured graphs:

| Case | Raw MSBuild graph | Graph/plugin | Retired native batch |
| --- | ---: | ---: | ---: |
| Fresh Restore + Build | 225.41 | 206.38 | 220.41 |
| Pipelines body edit | 18.55 | 17.13 | 148.16 |
| Pipelines API edit | 21.96 | 21.24 | 146.78 |

Cold runs clear outputs/packages and Bazel action/worker state. SDK/package archive
acquisition, sync, tool bootstrap and disk trim are unscored. Edits retain normal
local state; remote caches and profiling are disabled. Raw Build uses MSBuild's
graph API with the same roots, properties, packages, four nodes and stable paths.
All project dependencies are source-built. No tests run in these build timings.

All three cases match **412 DLL/PDB/resource files** by path and SHA-256. The body
edit preserves reference bytes; the API edit changes them. Neither edit reruns
Restore. The plugin retains all 42 evaluations and rebuilds **6 / 11** projects for
body/API edits. Separate body-edit binlogs show six `CoreCompile` calls for both
raw and plugin builds. The native batch rebuilds 38 main assemblies plus 39 distinct
localized satellite assemblies for three generators; these are not duplicate outputs.

The native body/API observations are **8.6× / 6.9× slower** than the graph/plugin
path. They are single observations, not repeated-pair medians or a full-runtime
baseline. An earlier frozen projection's 17.5% saving did not carry over to generated
source-built batches. The alternative backend and its configuration are removed;
raw reports and the experimental revisions remain outside this workflow.

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

### Source-runtime product

#### Ubuntu 26.04 / LLVM 18 qualification

One correctness workflow used Ubuntu 26.04 ARM64, four CPUs / 8 GiB,
SDK **10.0.400**, Bazel **9.3.2** and Clang **18.1.8**. A host/service interruption
stopped the first final managed Build. The supported resume retained the same
setup/source and reused all three completed native producers; it then finished
the managed product, archive and forced consumer tests.

| Phase | Observed wall time | Method / cache state |
| --- | ---: | --- |
| Initial managed preparation / qualification | 1,274.60 s | Separate initial phase; sync 1,118.92 s, sync-check 3.36 s |
| Resumed managed graph | 1,093.20 s total / 1,078.88 s execution | 563 project misses, zero hits; MSBuild execution, not pure Csc CPU time |
| Whole resumed Build stage | 1,474.28 s | Includes repeated offline 172-root Restore, managed graph above, layout/archive; native outputs cached |
| Forced consumer verification | 36.26 s | Two actual tests: app 0.2 s, runtime/product 34.2 s |

The 194-package declared compiler root passed C/C++ compile/link/run before the
full workflow. The product tests verify 172 source-framework members, producer
bytes/modes, SDK-absent execution and rejection when CoreCLR is removed. The
exported archive is 22 MiB. Raw reports retain image/toolchain/product hashes,
interruption evidence and guest memory observations. No uninterrupted total or
comparison with the historical HTTP-warm timings below is claimed. Source, SDK
and native producer boundaries are in [support](support.md#complete-source-runtime-product).

#### Complete-product Pipelines body edits

A separate instrumented trial used the complete Ubuntu 26.04 ARM64 source
runtime and app, SDK 11.0.100, Bazel 9.3.2, and the net10 source product at
[rules revision `ae39665`](https://github.com/keegan-caruso/msbuild-bazel/tree/ae3966592cb1294d7f1af6f290ab91a8b5ab34e9).
The Apple Container worker was configured for four CPUs and 12 GiB; the guest
reported five online CPUs. A fresh input-only workspace and output base used
seeded remote actions, remote project-cache read-only mode, and no Bazel uploads.
The run used one build job, one local test job, and one worker instance per
worker key; two broker processes remained stable across all cases. The separately
measured baseline populated the local project cache; it is not a cold-cache
measurement.

| Phase | Wall time | Project-cache results |
| --- | ---: | --- |
| Baseline | 1,483.45 s | 0 hits / 563 misses |
| Five body edits | p50 88.44 s; p95 100.65 s | 554 hits / 9 misses in every edit |

The p95 is the maximum under nearest-rank calculation for five samples. Each
case ran both app and runtime tests. Across the five edits, the source graph
had five owner variants; the nine aggregate misses do not identify which
variants missed. The broker processes and Pipelines reference DLL remained
stable. Each edit produced a different implementation DLL, and both normal
and SDK-absent executions loaded its verified hash. Native outputs and CoreLib
remained unchanged. The private fixture adds a probe and baseline marker; these
are not paired raw-MSBuild timings or a speedup comparison.

At 0.5-second sampling, guest available memory reached a minimum of 4.89 GiB
during the baseline and 6.99 GiB across the body edits; sampled cgroup memory
events showed no OOM. At measured command boundaries, the owned workspace and
output base occupied at most 7.80 GiB, excluding other guest and host storage.

The manual [trial harness](../tests/graph_build/upstream/README.md) requires a
qualified product and input-only closure, independently verified runtime-test
oracle, and exact qualification mappings. This run used mappings SHA-256
`cafe5a24781427a70d25e43d538969fadd21a5fe9e9047263b98ad9b23af01cf`
and corrected harness SHA-256
`40fe40321b73286914d830843f139fd6cf9468367bc5775294f181d99235e613`;
the corrected harness is available in [PR #204](https://github.com/keegan-caruso/msbuild-bazel/pull/204). The production rules
and trial harness are separate inputs.

#### Historical Ubuntu 22.04 qualification

One correctness run on Ubuntu 22.04 ARM64, four CPUs / 8 GiB, SDK 10.0.400 and
Bazel 9.3.0 used the complete 172-assembly / 16-native-file developer runtime:

| Phase | Wall time | Cache state |
| --- | ---: | --- |
| Initial sync / sync-check | 1,200.00 / 3.46 s | Fresh qualification / retained preparation |
| Declared runtime + app build | 225.27 s | Native compilation; 563 managed project hits |
| Producer tests | 37.40 s | Two actual test executions |
| Independent build recovery | 75.70 s | 138 remote spawn hits; one local package extraction |
| Consumer tests | 6.67 s | Two actual test executions |

The producer used a fresh pinned image, a supplied source archive and available
HTTP caches. The stopped-producer consumer received only **10,025 declared inputs**
(16 MiB compressed), source rules and hash metadata. Tools were bootstrapped;
verified repository downloads from an earlier analysis attempt were available.
No compiled outputs or local action cache transferred. The three graph actions,
Restore, three native builds and version generation were remote hits. All 649
runtime files match in bytes/modes, as does the complete archive. These single-run
controls are not paired raw-MSBuild comparisons or a cold-cache speedup claim.

A separate profiled replay with verified acquisition caches prepared and another
fresh output base took **51.06 s**, with the same cache counts and exact output
parity. Its source-repository extraction took **11.26 s**; package assembly took
about **4.2 s**. Repository setup and remote output downloads remain material.
Profile intervals overlap; these are diagnostics, not additional benchmark samples.

With reproducible SDK/source repositories, a fresh-base diagnostic replay took
**34.63 s** with the downloader disabled, identical product bytes and the same
138 remote hits / one local action. Neither repository was extracted again.
A control with the contents cache disabled extracted sources in 8.83 s and the
SDK in 5.37 s. These profiles overlapped other validation; use the removed
extraction events as evidence, not the wall times as a paired speedup.

A source-only sync consumer received **60,958 authored/control files** (91 MiB
compressed), with the producer stopped. A fresh output base recovered preparation
in **35.64 s**: 122 remote spawn hits, including `MSBuildSyncPrepare`, zero executed
spawns and byte-identical declarations. `sync --check` passed with cache misses
forbidden. This measures whole-action recovery; cached stdout can still contain
the producer's private-Build messages.

Qualification on this graph still needs a cold seed. Separate profiles with
HTTP project caching and Bazel disk/remote action caches disabled recorded:

| Qualification case | Bazel wall | Private SDK Build | Project hits | Csc tasks |
| --- | ---: | ---: | ---: | ---: |
| Empty project-cache seed | 1,316.98 s | 1,171.65 s | 0 | 691 |
| Fresh output base, unchanged sources | 90.39 s | 3.50 s | 563 | 0 |

The fresh-base control recovered Restore in 9.43 s without executing it. These are
single profiles, not paired scores. The [earlier forced-edit profiles](https://github.com/keegan-caruso/msbuild-bazel/blob/aa6749b/docs/performance.md#source-runtime-product)
also changed an unused input, so they do not isolate compiler-only invalidation.

For actual Pipelines edits, three alternating unprofiled pairs on the same VM,
SDK and runner compare conservative Restore keys with the two reviewed compiler-
content exemptions. Tools/packages and HTTP project snapshots were prepared;
Bazel disk/remote action caches were disabled. Median qualification times:

| Edit | Conservative Restore | Reviewed Restore reuse | Reduction | Csc tasks in both |
| --- | ---: | ---: | ---: | ---: |
| Body | 154.21 s | 89.65 s | 41.9% | 11 |
| Implementation/reference API | 158.53 s | 102.58 s | 35.3% | 26 |

Only compiler files and the compared mapping changed; there was no forcing file.
Distinct equivalent edits prevent cross-mode compilation hits. Every candidate
reused Restore; every baseline executed it. Each run reproduced ordinary sync's
JSON/Starlark byte-for-byte. Restoring the original sources recovered Restore and
all 563 projects with zero Csc tasks. These measure qualification, excluding
acquisition, update, product selection and cache seeding; ordinary-build timings
are separate.

Reproduce with the retained full `managed/source` workspace, not its pruned build
consumer. Its `//:sync` must enable `qualification_cache`. The helper restores
sources/mappings on exit; `--trim-between-rows` requires guest trim permission:

```sh
python3 benchmarks/runtime_qualification.py OWNED_RUNTIME_SOURCE FRESH_RESULTS \
  --mappings=sync-mappings.json --output-base=FRESH_BASE \
  --cache-url=http://cache:8080 --samples=3 --trim-between-rows
```

Source-runtime setup's `--cache-url` enables this reviewed reuse; standalone
preparation accepts `--qualification-cache` with
`RULES_MSBUILD_PROJECT_CACHE_URL` set. Other source contents remain conservative.

For that preparation handoff, run `close-sync SOURCE HANDOFF/workspace
--preparation-base=FRESH_BASE` with the helper below. It queries the exact sync
`srcs` rather than transferring private build products. Use the same remote cache
and a fresh consumer base; `--experimental_remote_require_cached` makes an
unexpected execution fail.

The [recovery helper](../tests/graph_build/upstream/runtime_product_recovery.py)
provides `close WORKSPACE HANDOFF/workspace` and `seed WORKSPACE HANDOFF/seed.json`.
Transfer the handoff and the matching rules checkout as `HANDOFF/rules`; stop the
producer. In the relocated workspace use the rules' `scripts/bazel-launcher.sh`
with a fresh output base, `--disk_cache=`, the same `--remote_cache`,
`--remote_cache_async=false`, `--remote_download_outputs=all`,
`--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=URL`, `--strategy=MSBuildGraph=worker`
and `--worker_sandboxing`. Build `//:app
//:runtime_package` with `--execution_log_json_file=ACTIONS`; run `check WORKSPACE
RESULT --seed=HANDOFF/seed.json --actions=ACTIONS`. Actually execute `//:app_test
//:runtime_test` with `--nocache_test_results`. This handoff requires a prepared
producer and the [qualified Linux environment](support.md#complete-source-runtime-product).

## Bounded cache controls

Native macOS ARM64, SDK **10.0.400**: `remote_streaming.py` fetches eight 8 MiB
payloads concurrently with a store budget of two. Its sampled managed-memory growth
was **3,359,440 bytes** for distinct payloads and **2,141,080 bytes** for shared
content; maximum active payload responses was **two**. The shared payload required
one GET, and an interrupted body recovered exact bytes on retry. These single
synthetic observations exclude the Python server's memory, native allocations and
package/build work; they are neither RSS budgets nor before/after speedups.

`publication_queue.py` uses controlled completion signals to verify capture can
continue with two active publications, admission blocks at capacity, and failures
drain started work. Concurrent distinct-key HTTP publications share one payload
PUT. No wall-time improvement is inferred from these concurrency controls.

The native ownership-index control classifies independent outputs and performs one
lookup per node. Single observations were **7.43 / 19.92 / 52.13 ms** at
**1,000 / 4,000 / 16,000 nodes**. The former conflict-free algorithm would visit
**999,000 / 15,996,000 / 255,984,000 ordered node pairs** before path comparisons;
these are operation counts, not a timed baseline. Run
`python3 -m unittest discover -s tests/project_sync -p test_input_observations.py -v`.

`python3 tests/analysis/runtime_layout_scaling.py` exercises the actual expansion
callback and compares output with the previous nested scan. Increasing files from
1,000 to 10,000 and selections from 101 to 1,001 required 3,000 to 30,000 prefix
probes, with nested member ordering preserved. This isolates prefix selection,
not complete Bazel action latency.

One native extraction of a generated 128 MiB uncompressed package used
**69,484,544 bytes peak RSS**, measured with macOS `/usr/bin/time -l`; the retained
archive and extracted payload matched their inputs. This is one bounded-memory
control, without a comparative baseline or whole-build timing claim. Private
verified staging adds temporary disk I/O while removing whole-archive managed
buffers.

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

## Sustained catalog application

A five-project package-backed catalog app was exercised on Ubuntu 26.04 ARM64,
SDK **10.0.400** and Bazel **9.3.2**. It includes Razor pages/API, JSON data, package
dependencies/analyzer, unit checks and published static assets. One guest was
configured for four CPUs and six GiB, with two Bazel jobs, one local test and one
worker instance per worker key. The guest reported five online CPUs; that observation
is separate from the configured allocation. No source-runtime production is timed
here.

Five distinct body edits and five distinct API edits each executed the app's HTTP
smoke and forced unit/web tests. Every body edit reused four projects and compiled
one; every API edit compiled four and reused one. Reference bytes stayed unchanged
for body edits and changed for API edits. Five Publish invocations and forced
published-product tests also passed. All **33 commands**, including separate
bootstrap/seed commands, succeeded; **25 test executions** were forced.

| Invocation | Observations | p50 | Nearest-rank p95 |
| --- | ---: | ---: | ---: |
| Body edit + app HTTP smoke | 5 | 1.435 s | 1.485 s |
| API edit + app HTTP smoke | 5 | 3.060 s | 3.225 s |
| Publish + app HTTP/static smoke, mixed initial/retained target | 5 | 1.428 s | 8.290 s |

These are whole Bazel invocations, including process/app startup and resource
monitoring, not individual HTTP-request latency. With five observations, p95 is
the maximum and is a weak tail estimate. The first Publish initialized that target
and took 8.290 s; the remaining four retained-target invocations took
**1.378–1.434 s**. Do not interpret the mixed Publish p95 as a warm-only tail.
SDK/package/sync bootstrap (**62.03 s**), sync-check (**3.94 s**) and initial Build/app
seed (**8.85 s**) are separate from the edit distributions. There is no paired
raw-MSBuild comparison or speedup claim.

Whole-guest memory was sampled every 0.25 s. Minimum available memory was
**4,966,104 KiB**; peak summed process RSS was **1,508,003,840 bytes**. RSS sums count
shared pages in each process and are not physical peak usage. Maximum observed
allocated disk at command boundaries was **535,314,432 bytes** for the owned
consumer/output base. This includes any SDK/repository expansions under that base,
excludes the image, preinstalled tools and other filesystem paths, and is not an
instantaneous disk peak. From the first completed Publish/test cycle to the final
cycle, that boundary total grew **200,704 bytes**.

The current four-CPU/six-GiB qualification cap remains unchanged. One small real
application and a short series cannot set a universal production budget or close
the separate sustained source-producer gate. Reproduce with the pinned tools in
the qualified guest, using a fresh owned directory outside the checkout:

```sh
python3 benchmarks/sustained.py OUTPUT --revision RULES_COMMIT --samples 5
```

The controller retains each command log, failures/timeouts, memory samples,
allocated-disk boundaries, graph observations and a summary. It explicitly selects
Build/Publish workers and uses no HTTP project-cache backend.
