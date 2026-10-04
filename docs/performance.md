# Performance versus raw MSBuild

Baseline **8d83f0f**, runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
SDK 10.0.400, Bazel 9.2.0, Linux ARM64: four CPUs / 8 GiB, four MSBuild nodes,
one graph worker with an 8192 MiB snapshot budget. Scope: 481 compilations /
543 configurations / 39 roots. Refreshed after the graph-only cutover.

Median wall seconds, three matched pairs, profiling off:

| Case | Bazel | Raw MSBuild | Difference |
| --- | ---: | ---: | --- |
| No-op | 0.39 | 17.43 | Bazel whole-action hit |
| Leaf body edit | 32.66 | 30.24 | 8.0% slower; six Csc calls each |
| Leaf API edit | 47.80 | 46.68 | 2.4% slower; 17 Csc calls each |
| Local project recovery | 20.07 | — | 481 hits; no compilation |

All 3,622 compiled files matched raw bytes on every row. Body/API edits reused
prepared Restore and had 475/464 project hits. Acquisition, the all-miss seed,
source restoration and filesystem trimming were outside scored observations.
Only one build VM ran during scoring. The incomplete series from a disk-damaged
VM was excluded; these rows came from a fresh filesystem and verified inputs.
Independent HTTP recovery on a fresh relocated container, with the producer
stopped and Bazel whole-action caches disabled, had **481 hits / zero misses**.
All 10,780 files matched bytes/modes. One unprofiled observation was **121.04 s**:
fresh prepared Restore took 95.65 s and graph recovery 23.13 s. Package/SDK
acquisition was excluded. Native-host setup and eight-suite execution were
separate; 118,952 passed / 64 skipped / zero failed, with matching normalized
producer outcomes and 3,568 source-product hash observations. The older 34.35 s
recovery below had warm preparation and is not the same timing scope.

One paired cold observation (raw first): graph **1061.33 s**, raw Restore + Build
**1056.91 s** (**0.4%** overhead). Raw Restore was 79.35 s and Build 977.55 s;
graph Restore/Build action spans were 95.21/958.18 s. All 3,622 compiled files
matched. SDK/packages and Bazel bootstrap were available; outputs and project
snapshots were fresh. This measures cold compilation, not first-time acquisition.

Separate body/API diagnostics measured evaluation **5.36/5.59 s**, input hashing
**2.74/2.75 s**, and replay copies **3.82/3.08 s** (689/677 MB). Worker staging was
1.00/1.08 s. These scopes can overlap; do not add operation totals as wall time.
Candidate dcbf44e (owned-product publication and reduced package inputs), same
resources and three-pair method:

| Case | Bazel median | Paired raw median |
| --- | ---: | ---: |
| No-op | 0.17 | 17.85 |
| Body | 34.44 | 31.05 |
| API | 48.37 | 45.34 |
| Local recovery | 18.43 | — |

All 3,622 files matched; body/API still had six/17 Csc calls and zero Restore
actions. Local recovery observed 18.04–19.68 s versus main's 20.07 s median.
These combined changes do **not** establish an edit-time speedup: raw times and
paired gaps varied too. Separate body/API diagnostics measured evaluation
5.96/5.53 s, replay copies 3.59/2.51 s (same 689/677 MB), staging 1.03/1.01 s,
and publication 0.15/0.16 s. Remaining work is evaluation and snapshot replay,
not publication. Retain Restore's contract: these edits already reuse preparation.
The fresh all-miss seed and diagnostics were excluded from scored pairs.

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

## Evaluation transfer qualification

`//tests/integration:evaluation_transfer` uses the production diagnostic counter
and forced out-of-process MSBuild nodes. On Linux ARM64 / SDK 10.0.400 / both
Bazel pins, partial transfer caused three build-node evaluations; full transfer
caused zero, with matching DLL/PDB bytes. Cached/uncached worker Build/Publish
controls also passed. This removes reconstruction within a request; the initial
graph still evaluates afresh. Reuse between requests needs a retained isolated
engine, pristine instance copies and a complete evaluation invalidation contract.
No large-runtime edit-time improvement is claimed for this slice.

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
