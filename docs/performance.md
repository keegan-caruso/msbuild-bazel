# Performance versus raw MSBuild

Production retained-evaluation runner **1bca5b1**, runtime v10.0.0
(`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400, Bazel 9.2.0,
Linux ARM64: four CPUs / 8 GiB, four MSBuild nodes, one graph worker.
Scope: 260 project paths / 543 configurations / 481 compilations / 39 roots;
8192 MiB project snapshots and a 1024 MiB evaluation retention budget.
Only the two reviewed Pipelines edit sources opt into compiler-only evaluation reuse.

Median wall seconds, three matched pairs per mode, alternating raw/graph order,
profiling off. Fresh controls disable retention and use equivalent unique edits.

| Case | Retained evaluation | Fresh evaluation | Raw MSBuild, retained / fresh pair |
| --- | ---: | ---: | ---: |
| No-op | 0.22 | — | 17.22 / — |
| Leaf body edit | 28.96 | 29.75 | 31.74 / 31.74 |
| Leaf API edit | 41.10 | 46.77 | 45.74 / 45.31 |

Retention reduced the observed body/API medians by **0.79 s (2.7%) /
5.67 s (12.1%)**. Body ranges: retained **26.91–29.07 s**, fresh
**29.21–31.41 s**. API retained **39.61–60.53 s**, fresh **46.48–48.67 s**;
the slow retained sample spent 50.25 s in execution despite reusing evaluation.
Three pairs establish these observations, not a guaranteed speedup.

All 3,622 DLL/PDB/resource files matched raw bytes on scored rows. Bazel freezes
published files to 0555; raw files remained 0644. No-op hit the whole graph action;
body/API reused prepared Restore, hit 475/464 projects and compiled six/17.
Retained edits loaded zero evaluations and reused all 543. Every request still
verified SDK/package/input bytes and used fresh MSBuild build nodes.
Forced local recovery had 481 hits / zero compilations, median **18.84 s**.
After an intentional compiler failure, recovery reevaluated all 543 configurations,
kept 475 project hits, recompiled six and matched all outputs (**31.67 s**, raw
**33.18 s**, one observation). Failed requests do not poison retained state.

Separate body/API profiles measured evaluation **5.75 → 1.64 s / 5.53 → 1.73 s**
(fresh → retained). Retained identity validation took **0.77/0.82 s**; fresh
instance construction still occurs. Retained worker staging was **1.04/1.10 s**,
publication **0.18/0.18 s**, and replay copies **3.47/4.43 s** for **689/677 MB**.
Scopes overlap and are not additive wall-clock components. Both modes made exactly
six/17 Csc calls; retained build nodes evaluated zero projects.

Post-request engine managed heap was **955/944 MiB**, RSS **1.18/1.25 GiB**;
neither request retired the engine. These are engine observations, not incremental
allocations or hard peak bounds. The 1024 MiB budget retires state between requests;
the production default is 512 MiB. Whole-VM samples include idle retained processes,
even during raw controls, so they cannot isolate a raw/graph memory difference.

Driver: `python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE RESULTS
--output-base BASE --slice runtime-suites --qualified-raw-results RAW_RESULTS
--evaluation-reuse --compare-fresh-evaluation --failure-recovery --diagnostics
--trim-between-rows`. The fixture's contract must explicitly inventory the two edit
sources; set its graph to `evaluation_cache_mb=1024`. This series qualifies local
retention/recovery, not a new independent remote-cache consumer or RBE run.

Acquisition, baseline restoration, engine priming, output comparison and filesystem
trimming were unscored. Only one build VM ran. The all-miss production seed took
1048.05 s including preparation and matched all outputs; scoring continued from
that verified cache. There is **no new paired cold comparison** for retention.

Earlier paired cold observation at **8d83f0f** (raw first): graph **1061.33 s**,
raw Restore + Build **1056.91 s** (**0.4%** overhead). All 3,622 files matched.
SDK/packages and Bazel bootstrap were available; outputs and project snapshots
were fresh. This measures cold compilation, not first-time acquisition.

## Complete remote-cache recovery

Snapshot replay now hashes bytes while copying them and reuses that verified
digest for dependency keys within the same request. Clone mode hashes the cloned
destination. Every path is still checked on every request, including omitted
payloads; no timestamp, inode or cross-request verification shortcut was added.

Six alternating warm pairs on the runtime's 10,780 files / 697 MB measured
hash + copy + dependency hash at **1.43 → 0.87 s** (median). Hash + copy alone
was **0.96 → 1.16 s**: the gain comes from removing the dependency reread.
These isolated serial probes exclude setup and establish no end-to-end gain.
Native `//tests/integration:snapshot_replay` controls cover copy/clone fallback,
same-size/mtime corruption, replacement inodes, modes, independent outputs and
byte parity with fresh compilation. `verifiedOutputDigest` counts reused digests;
verification now belongs to `snapshotReplay`, rather than `snapshotValidation`.
Replay, retained-worker and omission controls passed on both Bazel pins on a
fresh Linux ARM64 guest. Owned .NET/style and scaffold checks passed; direct
`tests/graph_build/replay.py` controls also rejected corrupted required/omitted
payloads and preserved Build/Publish parity.

Earlier fresh-evaluation qualification of the 481-compilation runtime contract,
Linux ARM64 / SDK 10.0.400 / Bazel 9.2: a fresh relocated consumer, producer
stopped, fresh output bases, normal Bazel HTTP caching enabled and local disk
caching disabled. After bounded child verification, one unprofiled observation
per case:

| Recovery | Wall seconds | Restore action | Graph action |
| --- | ---: | ---: | ---: |
| Whole-action hits | 9.86 | 2.60 remote hit | 1.86 remote hit |
| Forced graph execution | 29.15 | 2.65 remote hit | 22.49; 481 project hits / zero misses |
| Body edit | 29.14 | Reused | 26.95; 475 hits / six misses |
| API edit | 41.46 | Reused | 39.46; 464 hits / 17 misses |
| Return to original sources | 16.84 | Reused | 15.21; 481 hits / zero misses |

All 10,780 compared files matched bytes/modes on seed and recovery. The all-miss
seed took 1072.84 s; bootstrap/acquisition was separate. Edits preserved the
expected reference-assembly boundary and executed no Restore action. Independent
native controls passed on Bazel 8.8.0 and 9.2.0, including fresh tests.
Whole-action reports are cached producer metadata; spawn logs establish actual
recovery. Download mtimes changed MSBuild's `MSBuildAllProjects` prefix; keys now
represent that prefix by the complete validated import set without changing the
SDK instance. Authored entries and imported bytes remain significant.
The earlier 95.65-second Restore measurement deliberately disabled this action
cache; it does not describe normal recovery. This is cache recovery, not RBE or
a new runtime test-suite run.

Workers now copy preparation without a duplicate broker hash; the read-only
child verifies every payload before any Restore-output writes or evaluation.
Five paired fresh-copy probes on 8,979 files / 1.75 GB measured median
materialization **1.77 → 0.59 s**. These isolated operations used warm filesystem
caches; this does not establish a paired end-to-end speedup. Corrupt new/cached
copies, changed modes/inodes and invalid manifests failed the production checks.
A separate final diagnostic measured staging 2.94 s, child preparation 2.17 s
(SDK 0.76 s, Restore key 0.86 s, payload verification wall 0.31 s), evaluation
5.64 s and input hashing 2.55 s. Scopes can overlap. Large rows were not paired
against the serial implementation; they establish correctness, not a speedup.

Driver: `python3 tests/graph_build/upstream/runtime_complete_remote.py WORKSPACE
RESULTS --output-base BASE --cache-url URL --phase producer`. Stop the producer;
run a new consumer with `--phase consumer --seed-evidence PRODUCER/seed.json`.
`--edits` adds body/API and original-output recovery controls on the retained
worker; `--diagnostics` adds a separate profiled recovery. Native controls use
`//tests/integration:complete_remote_cases_bazel_8_8_0` (or
`_bazel_.bazelversion`), with `COMPLETE_CACHE_PHASE`, `COMPLETE_CACHE_URL` and a
matching consumer `COMPLETE_CACHE_SEED`; they also cover body/API edits and fresh tests.

Full-child verification probes use `python3 tests/graph_build/package_verification.py
RESULTS --workspace WORKSPACE --contract CONTRACT --sdk SDK --prepared PREPARED
--apply --samples 6`. Each sample starts a fresh process with read-only prepared
packages and absent Restore outputs. Setup rebinds only a disposable manifest key;
this isolates verification, not remote recovery. `--profile` reports preparation
phases; `--cold` drops page caches in a disposable Linux guest. Neither setup nor
MSBuild evaluation is timed. `--compare-runner OTHER_DLL` rotates candidate order.
Six warm / three cold, unprofiled pairs on the same four-core Linux ARM64 guest:

| SDK / payload hash threads | Warm median | Cold median |
| --- | ---: | ---: |
| Serial / serial | 1.23 s | 5.37 s |
| Serial / four | 0.75 s | 4.66 s |
| Four / four | 0.58 s | 3.84 s |

Each child checks 4,907 SDK files / 672 MB, 8,979 prepared files / 1.75 GB and the
Restore key. Four threads won the 1/2/4 probes; the cap follows available processors.
Ordered SDK hashing preserves the existing digest. Verification finishes before
any Restore writes or evaluation. SDK/payload digests already flow into graph
construction; mutable inputs are checked again after execution. Same-size/mtime
corruption, invalid paths/modes/manifests, conflicting destinations and replacement
inodes failed the production checks. Read-only binds do not establish cross-child
immutability. These are verification gains, not paired end-to-end build speedups.

Combined fingerprints now serialize the same JSON directly into `IncrementalHash`,
avoiding the full JSON string and UTF-8 array. `input_integrity.py` checks prior-key
compatibility, escaping, Unicode, long records and single-pass enumeration. Six
warm / three cold paired Apply probes measured **0.65 → 0.62 s** and
**3.92 → 4.00 s**: no material verification-time gain is claimed. File bytes still
use streaming SHA-256; every child reads them afresh. Native worker body/API and
recovery controls passed on both Bazel pins.

## Evaluation correctness controls

Linux ARM64 / SDK 10.0.400, both Bazel pins:

- `//tests/integration:evaluation_transfer`: forced out-of-process nodes evaluate
  three projects with partial transfer, zero with full transfer; DLL/PDB bytes match.
- `//tests/integration:evaluation_reuse`: 23 prototype controls compare compiled,
  reference and task outputs with fresh evaluation. Reviewed compiler edits reuse
  evaluation; definitions, evaluation reads, Restore/configuration and membership
  changes reset it. Failed builds/input mutation discard state.
- `//tests/integration:evaluation_worker`: production workers preserve byte parity,
  restart for changed definitions, reads, task DLLs and membership, recover from
  failures, retire at a 1 MiB budget and disable retention at zero. Fresh build
  nodes and cleared private scratch prevent task-state leakage. Retirement still
  preserves valid project snapshots. Private LocalApplicationData stays stable.

Prototype graph construction measured **43.19 → 1.05 ms** and **24.91 → 0.95 MiB**
allocated across eight reuse controls; verification/compilation were excluded.
Use the large paired series above for end-to-end results. Retention is opt-in;
source extensions do not establish compiler-only use. See [worker API](api.md#caching-and-workers).

## Optional replay intermediates

The runtime contract can omit **808 duplicate SDK `obj` DLL/PDB files / 93 MB**
from replay/publication. The all-miss seed, edits, recovery and final restoration
matched all **2,814 retained compiled files** against the complete raw control.
Reference assemblies and required target results remain protected. Snapshots still
store and verify omitted payloads; corruption in an omitted file fails recovery.

Same 481-compilation scope and scoring controls as the main baseline:

| Case | Bazel median | Raw median | Replay work removed (separate diagnostic) |
| --- | ---: | ---: | --- |
| Body edit | 31.01 s | 30.06 s | 796 copies; 689 → 596 MB |
| API edit | 46.03 s | 44.84 s | 784 copies; 677 → 586 MB |
| Local recovery | 15.06 s | — | 481 hits; no compilation |

Both edits retain six/17 compiler calls and reuse Restore. Copy bytes decrease
about **13.4%**, but scored edits remain roughly **3% slower than raw**; recovery
is near the 15.24-second main baseline. This qualifies reduced work, not an
end-to-end speedup. The contracts stay opt-in. Evaluation still takes about 5.8 s.

`RuntimeRawGraph.cs.txt`'s `replay-omissions` mode inventories generic SDK
intermediates whose bytes match final outputs. Qualification explicitly applies
the candidate contract; `runtime_benchmark.py --replay-omissions` allows only
those omissions, requires them absent from graph output and present in raw, and
compares every remaining compiled file. Changes to inputs, properties, ownership
or required products still fail. No production default or runtime-specific
omission heuristic was added.

Native replay controls and independent three-project HTTP recovery passed on
both Bazel pins with `COMPLETE_REPLAY_OMISSIONS=1`: producer stopped, 49 required
files matching bytes/modes, whole Restore/graph hits, forced project recovery,
body/API invalidation and fresh tests. The 481-compilation omission contract has
local recovery evidence; independent HTTP recovery for that larger contract
remains unqualified.

[Historical series at 7e22cd6](https://github.com/keegan-caruso/msbuild-bazel/blob/7e22cd67609f6ae5e1606fcae9dcf6e578c2db3b/docs/performance.md)
measured cold Restore + Build at 1093.53 s versus 1048.89 s raw, and independent
HTTP recovery at 34.35 s. Those measurements predate the graph-only cutover.

Match source, configurations, Restore/cache state, native products and resources.
Keep profiling off for scores and report compiler calls and project hits/misses.
Drivers: [cold](../tests/graph_build/upstream/runtime_cold.py),
[edits](../tests/graph_build/upstream/runtime_benchmark.py),
[recovery](../tests/graph_build/upstream/runtime_remote.py) (each accepts `--help`).
Use `--trim-between-rows` when thin VM disks need unscored reclamation. Keep
reports outside Git. See [support limits](support.md).
