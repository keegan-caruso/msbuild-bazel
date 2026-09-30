# Graph cache performance and qualification plan

## Objective

Reduce work around project-cache hits while retaining MSBuild semantics. Fresh
remote-cache consumers are the primary case; retained local state is an additional
optimization. Keep graph mode opt-in until correctness, capability and platform
gates pass. Do not remove the existing backend before its replacement qualifies.

Starting point: Orchard body edit rebuilds one project and reuses 201, with exact
compared output parity. The standalone runner measured 40.01 s versus warm raw
MSBuild's 15.87 s. API/generator output differences and native Linux sandbox
qualification remain open. See [performance](performance.md).

## Execution rules

For each change: small correctness fixture, larger measurement, review, commit.
Push validated checkpoints. Record failed checks and remaining gates honestly.
Use pinned tools and upstream revisions. CI remains manual-only. Do not weaken
input verification or hide output differences to meet timing targets.

## Ordered work

1. **Comparable baselines and profiling.** Separate warm incremental, fresh local
   recovery, fresh remote recovery and cold builds. Record restore separately and
   compare equivalent raw MSBuild states. Add opt-in phase timings and counters
   for hashing, verification, transfer, materialization, compilation and snapshot
   storage. Obtain three paired body/API samples on Orchard. The existing
   build/snapshot timer includes final input verification; the unassigned total
   is primarily restore/setup, not a separate final verification phase.
2. **Output parity.** Separate original differing outputs from downstream copies.
   Compare repeated raw, cache-disabled graph and replay builds. Explain or fix
   all 898 Orchard API/generator differences and two resource-cache JSON
   differences. Only narrowly justified nonsemantic normalization is acceptable.
3. **Fresh-consumer materialization.** Measure duplicate blobs and intermediate
   copies, share content-addressed payloads, qualify copy-on-write on real large
   workloads, and preserve current dependency-copy bindings. Validate exact file
   sets, bytes and permissions plus isolation from cache/output mutations.
4. **Immutable input hashing.** Produce reusable declared preparation manifests
   for SDK/package content. Share source hashes and remove repeated path work.
   Key reuse by content and tool identity, never only versions or timestamps.
   Changes to bytes, executable modes and configuration must invalidate.
5. **Reusable restore.** Separate preparation with explicit SDK/package/project,
   import, framework/RID and custom restore inputs. Body edits should reuse it;
   package/configuration edits must refresh it. Qualify relocation and offline
   recovery. Retain conservative behavior for incomplete custom contracts.
6. **Evaluation reuse.** First remove repeats within an invocation, then reuse
   immutable evaluated information across requests only with a complete key.
   Never reuse target-mutated project instances. Test file discovery, conditions,
   imports and configuration changes on synthetic and upstream graphs.
7. **Retained local state.** Introduce owned configuration-specific state with
   successful-build manifests, validity checks, obsolete-output cleanup,
   interruption/concurrency handling and fresh fallback. Only then integrate
   persistent workers. Do not simply remove the empty-output requirement.
8. **Linux isolation and remote recovery.** Qualify public Bazel 8.8/9.2 actions,
   independent producer/consumer workers, relocated paths, empty local caches,
   native sandbox and intended worker isolation. Exercise corruption, eviction,
   permissions, conflicts, concurrent writers and interrupted transfers. An Apple
   container that cannot run linux-sandbox does not satisfy this gate.
9. **Expand upstream qualification.** Orchard full CMS/Razor/tests/Publish;
   Avalonia generation/resources/native tools/tests; runtime beyond Pipelines to
   native construction and running an app; then source-built SDK/native publish.
   Cover body/API/tool/resource/package/configuration edits, multi-targeting,
   reference roles, friend assemblies and executable/MTP/VSTest tests. Dependency
   body edits must invalidate runtime tests even when compilation is reused.
10. **Readiness and defaults.** Consolidate correctness, timing, disk/memory and
    transfer results. Proposed targets: warm edits within about 20% of equivalent
    raw MSBuild and fresh recovery clearly faster than rebuilding. These are
    acceptance targets, not promised outcomes. Switch defaults only after the
    capability and qualification gates pass; remove the old path separately.

## Status

Steps 1–4 are in progress. The plan and the profiling/benchmark controls are
committed. Steps 3–10 remain open; candidate ownership indexing and native Linux
sandbox qualification are being tested.

### Measurement checkpoint

- Added opt-in operation totals and separate restore, execution, input verification
  and snapshot-save wall timers. Operation totals overlap across threads/nesting.
- `profiling.py` passes: off by default, unchanged cache identity and output bytes.
- Remote profiling reports acknowledged upload and downloaded CAS payload bytes
  and operation counts, including manifests. These exclude HTTP framing and
  retry traffic. `remote.py` passes the counters plus authentication, transient
  retries, parallel transfers, eviction repair and corruption rejection.
- `benchmark_lanes.py` passes warm/local, cold/empty and fresh HTTP-cache lanes,
  explicit restore timing, distinct repeated edits and exact synthetic parity.
- Three paired Orchard samples completed. Median runner/raw times are
  36.80/14.27 s for body edits and 120.22/81.75 s for API edits. Body edits
  hit 201 projects and rebuild one, with exact compared outputs. API edits
  hit nine and rebuild 193, with the same 898 differing paths in each sample.
  These compare fresh output recovery with warm raw builds, not identical
  filesystem states; the runner includes Restore and raw does not.
- Body phase medians: Restore 6.08 s, evaluation 4.69 s, input hashing 10.62 s,
  execution 7.92 s, final input verification 7.40 s and snapshot save 0.01 s.
  Phase medians need not sum to the median total. Replay copies about 1.99 GB
  across 16,250 files; cumulative copying takes 3.87–4.53 s. Concurrent snapshot
  validation totals 27.07–28.00 s, which is not additive wall time.
- Reproduce the series with `upstream_edits.py ... --samples 3 --only body api
  --profile`. Reports remain in `/tmp/graph-roadmap-baseline` on the test host.
  A small Linux tool bootstrap overlapped the final API sample; the first two
  API samples measured 119.59/120.91 s and agree with the third's 120.22 s.
- The isolated upstream generator check reproduces differing DLL/PDB bytes in
  repeated raw builds. Its random interceptor identifiers are the only generated
  source differences. A disposable deterministic-name probe produces identical
  DLL/PDB bytes and executes correctly. This identifies an upstream cause; it
  does not yet classify every full-Orchard output difference or authorize broad
  output normalization.

### Native Linux sandbox checkpoint

The public three-project graph passes `linux_bazel_remote.py --spawn-strategy
linux-sandbox` on Linux ARM64, SDK 10.0.400, in a dedicated Apple container
(4 CPUs, 4 GiB). Bazel 8.8 builds three projects; Bazel 9.2 with a fresh output
base recovers three remote hits, then a body edit gets two hits/one miss. Runner
bootstrap bytes match across both Bazel versions. The graph action retains its
nested stable-path bubblewrap sandbox.

The outer container requires `--masked-path NONE --read-only-path NONE` so
Bazel can mount guest `/proc`; no added Linux capabilities were needed. Only
the repository was mounted from the host, read-only. Default Apple-container
proc masking fails this probe. This is a real native sandbox action, but uses
a separate existing cache server. A subsequent run also passed with independent
producer and consumer VMs, unrelated checkout/workspace paths and empty local
project-snapshot/action caches. The producer used 8.8; the consumer used 9.2, hit all three projects,
then reused two after a body edit. Both bootstraps produced the same runner
SHA-256 (`5abdd7e63a477abe164ccc70a8840c2294acf522dcc93088ae9ab912135787e1`).
Use `--phase producer|consumer --fixture-id <same-fresh-UUID>` to reproduce.
Persistent-worker isolation and the full fault matrix remain open.

### Orchard parity checkpoint

The full controlled API edit passes with a disposable deterministic-name patch
to the pinned Orchard interceptor generator. All 896 DLL/PDB path differences
disappear; file sets match. The two remaining paths are
`rjsmcshtml.dswa.cache.json` and `rjsmrazor.dswa.cache.json`. Only one entry in
`InputHashes` differs; all other fields match, including empty `CachedAssets`
and `CachedCopyCandidates`. Production inputs and output comparisons are unchanged.

`upstream/static_web_cache.py` proves against the installed SDK that changing
only the generated apphost timestamp changes those discovery hashes, with the
assembly and empty discovered outputs unchanged. The SDK adds apphost as a
`None` item; JS discovery hashes candidate metadata including `ModifiedTime`
before filtering for `*.razor.js`/`*.cshtml.js`. See the upstream
[cache implementation](https://github.com/dotnet/sdk/blob/main/src/StaticWebAssetsSdk/Tasks/DefineStaticWebAssets.Cache.cs).
The local SDK target inspection and executable fixture establish the behavior
for 10.0.400; the linked main-branch source is explanatory, not a pinned artifact.

Run `upstream/orchard_deterministic.py WORKSPACE CONTRACT CACHE RESULTS` for the
full control and `upstream/static_web_cache.py` for the small SDK fixture.
The full control restores the two edited source files. Its successful report is
in `/tmp/graph-roadmap-orchard-deterministic`; an earlier disk-full run was
discarded, its source edits restored from the pinned checkout, and the completed
qualification VMs removed before rerunning. This explains the captured API
differences; it does not make the original upstream generator byte-deterministic
or qualify every CMS test/publish path.

### Ownership indexing

Project output ownership is indexed once from the validated contract. Snapshot
checks find a file's owner by walking its parent paths, then check dependency
membership. Actual accesses still resolve paths to reject symlinks.

Three Orchard body samples with the candidate measured 21.63 s median versus
13.17 s raw, with 201 hits/one miss and exact compared output parity. Repeating
the original binary under the warmer filesystem conditions measured 25.67 s
median: a 4.04 s / 15.7% reduction. Execution fell from 7.87 to 3.85 s, while
hashing and verification were similar. Concurrent validation totals fell from
about 24.94 to 5.88 s; those are overlapping operation totals, not wall time.
The earlier 36.80 s baseline had slower filesystem reads and should not be used
to attribute the full improvement to this change.

The repeat control reused snapshots from before the temporary generator edit
and retained the explained 898 differences; the candidate's fresh seed and all
three body comparisons matched exactly. Reports are in
`/tmp/graph-roadmap-ownership-timing` and `/tmp/graph-roadmap-warm-control`.
`output_files.py`, reviewed dependency/multi-target controls and replay tests
pass, including forged ownership and newly introduced output-directory symlinks.

A cache inventory across 986 retained experiment snapshots found 27,637 stored
files, 4,442 distinct hashes, 4.41 GB of logical payloads and 1.36 GB of unique
content. This is storage evidence across several builds, not a measurement of
one remote recovery. Shared blob storage and the large COW comparison remain open.

### Input verification and fingerprint metadata

Each validation pass resolves common ancestors once; the final pass uses a fresh
set so links introduced during execution are still rejected. Evaluation checks
and both fingerprints share resolved paths, and project/item metadata is
serialized once per node. SDK identity now includes executable bits as well as
bytes. Every declared input is still content-checked after execution.

Three Orchard body samples measured 21.04 s median versus the ownership-only
candidate's 21.63 s: 0.59 s / 2.7% lower. Raw measured 13.24 s. All three had
201 hits/one miss and exact compared outputs. Input hashing fell from 5.11 to
4.47 s; final verification remains about 1.78 s. Reports are in
`/tmp/graph-roadmap-input-timing`. This is a modest saving, not the full immutable
preparation design. Persistent cross-build digest reuse remains unqualified.

`input_integrity.py` passes byte changes with preserved timestamps, SDK executable
bits, new ancestor symlinks and rejection of target input mutations before
snapshot publication. The source/import, ownership, reviewed dependency,
multi-target, replay and profiling tests also pass.
