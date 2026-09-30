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

All ten steps are pending at plan creation. Update this section with completed
work, measured results and explicit remaining blockers as execution proceeds.

### Measurement checkpoint

- Added opt-in operation totals and separate restore, execution, input verification
  and snapshot-save wall timers. Operation totals overlap across threads/nesting.
- `profiling.py` passes: off by default, unchanged cache identity and output bytes.
- `benchmark_lanes.py` passes warm/local, cold/empty and fresh HTTP-cache lanes,
  explicit restore timing, distinct repeated edits and exact synthetic parity.
- Three paired Orchard body/API samples are in progress. The first body sample
  measured runner/raw 36.73/14.27 s, 201 hits/one miss and zero differing outputs.
  Initial hashing was 10.70 s, final verification 7.38 s, execution 7.92 s,
  restore 5.97 s, evaluation 4.65 s and snapshot save 0.01 s.
- The isolated upstream generator check reproduces differing DLL/PDB bytes in
  repeated raw builds. Its random interceptor identifiers are the only generated
  source differences. A disposable deterministic-name probe produces identical
  DLL/PDB bytes and executes correctly. This identifies an upstream cause; it
  does not yet classify every full-Orchard output difference or authorize broad
  output normalization.
