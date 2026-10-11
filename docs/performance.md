# Performance versus raw MSBuild

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
