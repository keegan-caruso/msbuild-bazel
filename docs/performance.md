# Performance versus raw MSBuild

Baseline **69b2ac2**, runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
SDK 10.0.400, Bazel 9.2.0, Linux ARM64: four CPUs / 8 GiB, four MSBuild nodes,
one graph worker with an 8192 MiB snapshot budget. Scope: 481 compilations /
543 configurations / 39 roots.

Median wall seconds, three matched pairs, alternating order, profiling off:

| Case | Bazel | Raw MSBuild | Difference |
| --- | ---: | ---: | --- |
| No-op | 0.25 | 17.37 | Bazel whole-action hit |
| Leaf body edit | 29.61 | 29.55 | 0.2% slower; six Csc calls each |
| Leaf API edit | 44.63 | 44.43 | 0.5% slower; 17 Csc calls each |
| Local project recovery | 15.24 | — | 481 hits; no compilation |

All 3,622 compiled files matched raw bytes on every row. Body/API edits reused
prepared Restore and had 475/464 project hits. Acquisition, the all-miss seed,
source restoration and filesystem trimming were outside scored observations.
Only one build VM ran during scoring. These rows establish current parity;
differences from older runs are not a paired attribution of individual changes.

Median maximum VM used memory was **1.05/2.34 GiB** for no-op,
**2.94/2.53 GiB** for body and **3.04/2.85 GiB** for API (Bazel/raw).
Samples use `MemTotal - MemAvailable` every 250 ms: whole-VM pressure,
including retained processes/caches, not process RSS or managed allocation.

Separate body/API diagnostics measured evaluation **5.64/5.92 s**, input hashing
**2.14/2.29 s**, replay copies **2.16/2.88 s** (689/677 MB), worker staging
**1.17/1.25 s** and publication **0.15/0.16 s**. Build-node evaluation remained
zero. Operation scopes overlap; these are not additive wall-clock components.

Earlier paired cold observation at **8d83f0f** (raw first): graph **1061.33 s**,
raw Restore + Build **1056.91 s** (**0.4%** overhead). All 3,622 files matched.
SDK/packages and Bazel bootstrap were available; outputs and project snapshots
were fresh. This measures cold compilation, not first-time acquisition.

## Complete remote-cache recovery

Same 481-compilation runtime contract, Linux ARM64 / SDK 10.0.400 / Bazel 9.2:
a fresh relocated consumer, producer stopped, fresh output bases, normal Bazel
HTTP caching enabled and local disk caching disabled. After bounded child
verification, one unprofiled observation per case:

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

## Evaluation transfer qualification

`//tests/integration:evaluation_transfer` uses the production diagnostic counter
and forced out-of-process MSBuild nodes. On Linux ARM64 / SDK 10.0.400 / both
Bazel pins, partial transfer caused three build-node evaluations; full transfer
caused zero, with matching DLL/PDB bytes. Cached/uncached worker Build/Publish
controls also passed. This removes reconstruction within a request; the initial
graph still evaluates afresh. Reuse between requests needs a retained isolated
engine, pristine instance copies and a complete evaluation invalidation contract.
No large-runtime edit-time improvement is claimed for this slice.

## Evaluation reuse prototype

`//tests/integration:evaluation_reuse` qualifies a retained evaluator on the
three-project Linux ARM64 / SDK 10.0.400 fixture, on both Bazel pins. Each of
23 cases compares DLL/PDB/reference and task-output bytes with fresh evaluation.
Reviewed unchanged/body/API/source-timestamp cases perform zero evaluations
versus three fresh; project/import/Restore/configuration/evaluation-read and
file/directory membership changes reset the epoch. Failed builds and input
mutations discard state; changed SDK/runner/environment identity requires restart.
Every request still hashes SDK and input bytes afresh. Build nodes evaluate zero
projects. Fresh `CreateProjectInstance` snapshots preserve task registrations and
relative item metadata; `DeepCopy` failed the unprimed relative-reference control.

Across eight reuse controls, graph construction had medians **43.19 → 1.05 ms**
and **24.91 → 0.95 MiB** allocated. SDK/input verification and compilation are
excluded; these phase results do not establish a large-build speedup.

This is a retained-engine correctness prototype. Production workers still launch
fresh MSBuild. Stable namespace updates, loaded-tool identity, memory bounds and
large-graph qualification must precede production integration. Evaluation-read
contracts are explicit: source extensions alone cannot establish compiler-only use.

## Optional replay intermediates

`//tests/integration:replay_omissions` passed on Linux ARM64 / both Bazel pins.
The three-project fixture omits duplicate `obj` DLL/PDB files: six fewer copies,
329,517 → 285,005 replayed bytes (13.5%), with matching app/reference bytes,
unchanged body/API invalidation and uncached parity. Complete snapshots retain
omitted payloads; the replay control rejects corruption even in an omitted file.
This is a small work-volume result, not an end-to-end timing or large-runtime
speedup. Independent HTTP recovery with this contract remains unqualified.

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
