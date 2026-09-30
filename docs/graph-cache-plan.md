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

The plan is not complete. Current gates, in execution order:

| Step | Current result | Remaining gate |
| --- | --- | --- |
| 1. Baselines | Paired body/API series and explicit package/cache states | End-to-end large worker/remote timings |
| 2. Parity | Orchard generator and resource-cache differences explained with controls | Full upstream test/Publish parity |
| 3. Materialization | Ownership index and shared CAS implemented; COW measured | Broad fresh remote recovery measurements |
| 4. Inputs | Shared path checks and read-only worker packages qualified | Large-tree timing; cross-request SDK digest reuse |
| 5. Restore | Declared preparation and generated facade qualified | Orchard preparation remains slower; measure read-only candidate |
| 6. Evaluation | Shared context per invocation; inactive IDE items omitted | Complete safe key for cross-request reuse |
| 7. Owned state | Retention and worker broker qualified on small graphs | Retention has no measured wall-time benefit; large capacity sizing |
| 8. Linux/remote | Native sandbox, independent workers and fault controls pass on ARM64 | Broader platform and upstream coverage |
| 9. Upstreams | Orchard CMS Build and expanded Avalonia SimpleTheme controls | Full tests/Publish, runtime native construction, source SDK/native publish |
| 10. Readiness | Evidence consolidated; existing defaults retained | Performance and capability gates still fail |

Do not retain target-mutated MSBuild instances to close step 6. The worker still
starts a fresh MSBuild child per request; stronger reuse requires a complete
input contract and the same tool/package invalidation controls. Do not present
the small worker or managed runtime slice as source-built SDK qualification.
Larger qualification currently needs more disk capacity; old qualification
containers are retained pending the user's cleanup decision.

## Report summary

### Performance

Orchard measurements use SDK 10.0.400 on macOS ARM64, four MSBuild nodes and
202 configured projects. Each body sample reuses 201 projects and rebuilds one.
Times below are three-sample medians. Graph recovery starts with fresh declared
outputs and local snapshots; raw MSBuild keeps warm outputs and excludes Restore.
These are standalone runner measurements, not end-to-end Bazel or remote timings.

| Measurement | Graph | Paired raw | Meaning |
| --- | ---: | ---: | --- |
| Initial body baseline | 36.80 s | 14.27 s | Includes Restore, hashing and recovery |
| Initial API baseline | 120.22 s | 81.75 s | Nine hits, 193 rebuilds |
| Shared-evaluation body, retained packages | 19.18 s | 13.45 s | Latest measured ordinary retained-package candidate |
| Body, fresh expanded packages | 23.27 s | 13.83 s | Offline Restore expands the declared package feed |
| Prepared Restore, fresh packages | 35.75 s | 13.49 s | Slower than ordinary Restore; remains opt-in |

The original baseline had slower filesystem reads. Attribute changes using the
closer controls: ownership indexing reduced 25.67 to 21.63 s; path/hash metadata
reuse then measured 21.04 s. Shared evaluation reduced evaluation/check time
from 4.46 to 4.09 s; its total 20.21-to-19.18 s change also includes faster reads.
Do not attribute the entire historical reduction to code changes.

Fresh-package time splits into Restore 8.84 s, evaluation/checks 4.11 s, hashing
4.54 s, execution 3.97 s and final verification 1.78 s. Prepared recovery spends
14.45 s applying preparation and 10.90 s verifying inputs. Phase medians need not
sum to the median total. The later read-only worker package change has correctness
evidence but no large-workload timing yet; include broker materialization and
full Bazel wall time when measuring it. These timings predate that change and
the inactive-item fix. The roughly 20% overhead target is not met.

COW reduced cumulative copying but had only a small execution-time effect
(3.54 to 3.36 s); the whole 20.23-to-19.21 s result also includes faster hashing.
All six comparisons matched outputs. Linux retained outputs reduced copying
from 128.34 MB to 1.86 MB on 128 projects, but body time was unchanged
(4.14 s fresh versus 4.15 s retained). Copy remains the default; retention is opt-in.

### Correctness and removed work

- **Orchard parity:** random interceptor names explain the captured 896 DLL/PDB
  path differences, including downstream copies. A disposable deterministic-name
  control eliminates them. The remaining two resource-cache JSON differences
  contain apphost timestamp hashes with identical empty discovered assets.
  Production outputs are not normalized. Later unmodified runs retain these
  differences; this is not a general byte-determinism claim.
- **Directory inputs:** declaring empty `wwwroot` fixes a separate, real
  static-asset discovery mismatch. Full Orchard body controls then match compared
  outputs. Directory existence participates in cache identity and final checks.
- **Snapshot storage:** shared CAS eliminates repeated payload storage/downloads.
  A measured inventory has 16,946 payload paths / 2.65 GB logical data but only
  3,423 blobs / 0.76 GB distinct content. This spans builds, not one recovery.
  A small remote check downloads 35 payloads instead of 44 per-snapshot requests.
- **Input checks:** ownership is indexed once; common path ancestors and fingerprint
  metadata are shared within a pass. Fresh final checks still reject changed
  bytes, modes, new symlinks and target mutations. Timestamps do not authorize reuse.
- **Evaluation:** one shared context per graph pass reduces repeated work.
  Skipping false-condition IDE items prevents Avalonia's disabled platform globs
  from scanning the filesystem root. New imports/globs and changed conditions
  still refresh. No target-mutated project is reused across requests.
- **Prepared packages:** live Linux workers retain verified private preparation
  keyed by complete Bazel input digests and manifest bytes. Each child validates
  payloads, then uses a read-only package mount, avoiding a workspace copy and
  final package rehash. Changed bytes with an unchanged manifest are rejected;
  absent protocol digests force a fresh copy. The cache budget covers preparation
  and snapshots; zero-budget eviction and interruption cleanup are checked.
- **Isolation:** each worker request gets a fresh workspace, MSBuild process,
  PID namespace and `/proc` view. Read-only package writes fail; mutable inputs
  retain final verification. Retained evaluated projects and task assemblies are
  not part of this implementation.

### Qualification

| Scope | Verified result |
| --- | --- |
| Independent Linux workers | Bazel 8.8 producer stopped; relocated 9.2 consumer with empty local caches gets three remote hits, then two hits/one miss after a body edit. Runner bytes and executed values match. |
| Native Linux sandbox and workers | Bazel 8.8/9.2 pass Build/Publish, failed-build recovery, property invalidation and parity against fresh native actions. Private PID isolation also passes generated-preparation and same-VM remote reruns. |
| Tasks and tests | Normal/out-of-process task hosts and native generator implementation/data/mode controls pass. Dependency body edits retain identical reference assemblies and cached test compilation, but MTP/VSTest rerun and observe the changed implementation. |
| Avalonia SimpleTheme | Revision `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`: 11 physical projects, 29 configured nodes, 23 compiled nodes, 81 pinned package versions. Fresh HTTP recovery gets 23 hits with matching compared bytes/modes. |
| Avalonia edits | XAML: 22 hits/one miss and runtime style count changes from one to two. Body/API: seven hits/16 misses each. Generator: five hits/18 misses. Each matches a fresh native control; `.AssemblyReference.cache` is excluded. |
| Package inventories | Explicit graph-wide multi-version inventories pass separate-version resolution and upgrade controls. Default locks and per-project consumers still reject ambiguous versions and conflicting declarations. |
| Integrity and faults | Corruption, eviction repair, permission restoration, concurrent local publication, interrupted transfers, owned-state SIGKILL recovery and input mutations have focused controls. HTTP conflict prechecks cannot guarantee atomic competing publication without server-side compare-and-swap. |
| Repository checks | Owned-code/style checks, 54 ProjectSync tests, 47 Bazel analysis tests and scaffold/Starlark checks pass at their recorded checkpoints. CI was not run. |

Linux evidence is ARM64 in Apple containers; it does not establish x86-64 or RBE
support. Native sandbox qualification requires the documented guest `/proc`
configuration. Avalonia results cover SimpleTheme and dependencies, not all
applications/tests/native deployment. The generic runtime runner still has only
the bounded managed Pipelines slice; older per-project native/runtime results do
not qualify the new graph backend. Full upstream tests/Publish and source SDK
remain open. See [migration contracts](project-cache-migration.md).

### Invalid runs and reproduction

The first fresh prepared-Restore series accidentally reused all 202 snapshots.
It is excluded; the corrected series uses distinct edits and
`--expected-misses 1`. A disk-full Orchard parity run and the interrupted Avalonia
tool case are also excluded. Sources were restored; their replacement controls
passed. Overlapping setup/correctness runs are not scored as performance results.

Use `tests/graph_build/upstream_edits.py ... --samples 3 --only body api --profile`
for paired edits, adding `--package-state fresh --expected-misses 1` for body-only
fresh-package recovery. `upstream/orchard_deterministic.py` and
`upstream/static_web_cache.py` reproduce parity attribution.
`upstream/avalonia_worker.py WORKSPACE RESULTS --output-base PATH` checks the
prepared SimpleTheme fixture; `--seed-evidence` and `--only` support independent
recovery and scenario reruns. Linux worker controls are `linux_worker.py`,
`linux_bazel_remote.py --graph-worker --spawn-strategy linux-sandbox`, and
`linux_prepared_restore.py --worker --package`. Test prerequisites remain in the
individual fixtures; use pinned sources and disposable workspaces.

Raw logs, manifests and comparisons currently live under `/tmp/graph-roadmap-*`
on the qualification host. They are not checked into Git or durable public
artifacts. This summary preserves the conclusions, rejected runs and limits;
[performance](performance.md#current-graph-cache-optimization-checkpoint) is the
short timing scorecard. The status table above lists the remaining work.
