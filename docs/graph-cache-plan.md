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

Steps 1–2 have measured checkpoints. Steps 3–5 and 8 have partial
implementation and qualification; step 6 has within-invocation reuse.
Step 7 has an opt-in owned-state prototype and a qualified small Linux cache
broker. Cross-request evaluation/input reuse, larger worker qualification and
steps 9–10 remain open. Ownership
indexing and input-check improvements are committed and pushed. Prepared Restore
is opt-in and has not passed the large-workload performance/parity gates.

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

### Prepared Restore qualification

Added an opt-in declared Restore artifact and generated facade integration.
Standalone and generated three-project fixtures pass body reuse, fresh output
recovery, custom Restore data, package/configuration/environment invalidation,
corruption rejection and rejection of unsafe absolute-path relocation.
Native Linux ARM64 Bazel 9.2 execution logs show one Restore action for the seed,
none for a body edit, and one after a props change; the app prints the expected
value in each case. Bazel tree-input symlinks are resolved before the nested
read-only mount, and normalized payload modes are restored from the manifest.

The first three Orchard body samples measured 26.56 s median versus 13.19 s
warm raw MSBuild. Applying and validating preparation took 13.40 s; evaluation
4.17 s, remaining input hashing 2.15 s, execution 4.43 s and final verification
2.32 s. Preparation itself took 22.52 s. Each sample had 201 hits/one miss.
This is slower than the prior 21.04 s runner result. Repeated payload validation
and existing-workspace checks outweigh the saved Restore work in this lane.
The follow-up shares ancestor checks within each validation pass but has not
been remeasured on Orchard.

Three static-web-asset manifests differed. The fresh staging lacked the app's
empty `wwwroot` directory; after raw execution it existed. The cached seed
therefore omitted that discovery root. This is an input-discovery correctness
limit, not harmless JSON noise. Declare and reproduce directory existence before
qualifying this workload; do not normalize these manifests. No production
normalization or default change was made. Reports, exact contract and differing
JSON remain in `/tmp/graph-roadmap-restore-timing`; completed output copies were
removed to recover disk space.

### Directory-existence follow-up

Version-4 graph contracts can declare `InputDirectories`; graph sync mappings
use `inputDirectories`. Presence is staged before Restore/evaluation and included
in fingerprints. Files remain individually declared. The small Web SDK test
passes raw/replay static-asset discovery parity, recreation after removal,
contract-change invalidation, generated mappings, output/file/link rejection,
and rejection when a target deletes the directory. The full Orchard follow-up
is pending. This closes the representation gap without treating differing
static-asset manifests as equivalent.

### Evaluation reuse design

The graph callbacks currently call the `Project` constructor without an
`EvaluationContext`. The public `Project.FromFile` / `ProjectOptions` API allows
one shared evaluation context for a graph construction pass. Test this first for
shared SDK resolution and filesystem observations, then discard the context
before targets run or another request starts. Do not retain mutable projects or
filesystem observations across edits. MSBuild documents the API in
[ProjectOptions](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.definition.projectoptions?view=msbuild-18-netcore)
and [EvaluationContext](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.context.evaluationcontext?view=msbuild-18-netcore).
The within-invocation implementation and measurements are recorded below;
cross-request reuse remains unqualified.

### Large copy-on-write comparison

The directory-input candidate passes all six Orchard body comparisons: exact
compared file sets/bytes, 201 hits and one miss each. Three copy samples measured
20.23 s median versus 13.63 s raw; three subsequent clone samples measured
19.21 s versus 13.30 s raw. All 16,250 materializations cloned successfully with
no fallback. Cumulative materialization time fell from 4.80 to 3.89 s, but graph
execution wall time fell only from 3.54 to 3.36 s. Input hashing was also 0.63 s
faster in the later samples. Do not attribute the whole 1.02 s improvement to
cloning; copy remains the default. The mutation-isolation replay fixture passes
with clone mode. Reports and exact inputs are in `/tmp/graph-roadmap-large-copy`
and `/tmp/graph-roadmap-large-clone`.

The explicit empty-directory contract resolves the observed Orchard static-asset
parity difference for this body-edit series. This does not complete every test,
resource, Publish or prepared-Restore qualification case.

### Shared snapshot payloads

The candidate stores local payloads by content hash and links them only inside
the snapshot cache. Replay still copies or clones into writable project outputs
and restores each output's recorded mode. Filesystems without hard links fall
back to copies. Remote recovery uses the same store and serializes requests for
the same hash, downloading each distinct payload once across project snapshots.
All payloads are byte-checked; this does not skip input or snapshot validation.

Focused tests pass storage sharing with different output modes, output mutation
isolation, corruption rejection, twelve independent blob writers, conflict
rejection, and cleanup after failed publication or truncated transfers. Existing
replay, input integrity, and owned-code checks pass. Local and remote snapshot
publication accept an identical concurrent entry and reject a conflicting one.
The HTTP action-cache service still has no atomic compare-and-swap contract for
competing publishers; the pre-publication conflict check is not a guarantee
against every server-side write race. Native Linux and large-workload results
remain separate qualification gates.

The updated shared-payload candidate also passes `linux_bazel_remote.py
--spawn-strategy linux-sandbox` on Linux ARM64: Bazel 8.8 seeds three misses;
9.2 with a new output base gets three remote hits, then two hits/one miss after
a body edit. Executed app values and runner bytes match. This rerun used one VM
and the existing separate cache service; the earlier independent-VM result
predates payload sharing. Log: `/tmp/graph-roadmap-linux-payload.log`.

### Shared evaluation checkpoint

The runner and graph sync now use one MSBuild shared evaluation context per
graph construction. They create a fresh context for the next invocation and do
not reuse target-mutated instances. The same-process fixture passes new imports,
new source globs, edited import bytes and mutated-instance isolation. Owned-code,
configured-graph, prepared-Restore, directory-input and profiling checks pass.

Three Orchard samples measured 19.18 s median versus 20.21 s for the otherwise
identical isolated-context payload-sharing runner. Evaluation plus contract
checks fell from 4.46 to 4.09 s (0.36 s / 8.2%); the candidate's project evaluation
alone was 3.30 s. Hashing and raw MSBuild were also faster in the later series,
so do not attribute the full 1.02 s wall-time change to context sharing.
Raw medians were 13.85 and 13.45 s respectively. All samples reused 201 projects.

The isolated series matched outputs exactly. The shared series matched its first
sample; the next two had 44 DLL/PDB differences. A subsequent full body control
with the previously documented deterministic interceptor-name patch had exact
compared output parity. This is consistent with Orchard's upstream generator
nondeterminism; the unmodified results still retain their differences. The
control ran alongside small correctness checks and is not a scored timing run.
Reports: `/tmp/graph-roadmap-evaluation-isolated`,
`/tmp/graph-roadmap-evaluation-shared`, and
`/tmp/graph-roadmap-evaluation-deterministic`.

### Benchmark package state and storage

`upstream_edits.py --package-state fresh` removes only the disposable graph
workspace's expanded `.nuget` tree before each graph run; `retained` remains the
default. The report records this separately from output/cache state and raw
Restore timing. The warm/local, cold/empty and remote synthetic lanes pass with
fresh package state and exact compared outputs. Earlier Orchard measurements,
including the first prepared-Restore comparison, retained expanded packages.
They must not be presented as fresh Bazel-action package recovery costs.

The content-sharing cache after three Orchard qualification series contains
613 snapshots and 16,946 payload paths: 2.65 GB of logical snapshot payloads map
to 3,423 blobs / 0.76 GB of distinct data. This is measured storage across builds,
not transfer volume or the size of one recovery. Reports remain outside Git.

### Retained-state and worker boundaries

The first retained-state slice is Linux-only and opt-in through
`RULES_MSBUILD_GRAPH_LOCAL_STATE`, with metadata outside a disposable workspace.
It claims only initially empty outputs, locks both workspace and metadata,
marks work incomplete before Restore, and clears incomplete or obsolete owned
state. Hits verify existing bytes and restore recorded modes; misses clear their
project outputs before MSBuild executes. Linked outputs are replaced rather
than retained. This avoids stale timestamps suppressing required compilation.
The Linux fixture passes corruption/obsolete-file repair, permission repair,
body/API propagation, configuration/Publish changes, competing metadata owners,
and actual SIGKILL recovery. The 128-project comparison is recorded below. Larger
payload timing remains pending.

Persistent-worker integration must preserve these boundaries. Reuse immutable
SDK/input preparation only under owned, read-only mounts and complete Bazel input
identities. A fresh evaluation context is required per request. Third-party task
assemblies loaded at stable paths can outlive their bytes in a reused process;
restart or use a fresh MSBuild child when task/package implementations change.
Do not infer general worker safety from SDK-only projects. Qualify the public
worker protocol and sandbox first, then expand through task/analyzer/package,
Web/Razor, test and Publish controls before changing defaults.

The 128-project Linux ARM64 test completed three body and three API pairs per
mode. Fresh recovery measured 4.14 s body / 4.44 s API, versus raw 5.44 / 5.46 s.
Retained outputs measured 4.15 / 4.43 s, versus raw 5.35 / 5.34 s. Restore is
excluded from both engines in this harness. Body copying fell from 18,165 files /
128.34 MB to 254 files / 1.86 MB, with 17,911 outputs retained after byte checks.
There is no meaningful wall-time win at this size. Keep retention opt-in and
measure larger payloads before exposing it in public rules. Every edit asserts
expected miss counts and runs the app. Reports:
`/tmp/graph-roadmap-fresh-state-timing.json` and
`/tmp/graph-roadmap-retained-state-timing.json`.

The final remote counter check downloaded 35 distinct payloads instead of 44
per-snapshot requests, transferring 212,950 bytes including manifests. The
comparison counts each hash once per snapshot, matching the previous transport.

### Fresh package expansion baseline

With `.nuget` removed before each graph invocation, three Orchard body samples
measure 23.27 s median versus 13.83 s warm raw MSBuild. Restore is 8.84 s;
evaluation/checks 4.11 s, input hashing 4.54 s, execution 3.97 s and final
verification 1.78 s. All reuse 201 projects and rebuild one. File sets match;
compared byte differences remain 898/44/898 across samples, consistent with the
recorded upstream generator issue. This is fresh expanded-package recovery,
not a package download measurement. Reports: `/tmp/graph-roadmap-fresh-packages`.

### Persistent cache broker checkpoint

The public graph rule and generated facade now offer an opt-in Linux singleplex
worker. It retains only the private snapshot cache, using a fresh workspace and
sandboxed MSBuild process for every request. This avoids cross-request task
assembly/evaluation state. Retained project outputs remain a separate experiment;
the 128-project result did not justify enabling them in the worker.

`linux_worker.py` passes under `--worker_sandboxing` on Bazel 8.8 and 9.2, including
body reuse, compilation-failure recovery, definition-change rejection/resync,
property invalidation and exact compared output parity against a fresh native
sandbox. `tools.py --graph-worker` passes implementation/data changes with both
task-host modes. Generated prepared Restore also passes through the worker.
An initial task-data assertion failed because it required a leading newline;
the captured output was correct (`43`), with changed data and a cache miss.
The assertion now compares lines. Owned-code and Starlark checks pass.

Large worker timing, retained SDK/input preparation, capacity policy and broader
Web/test/Publish checks remain open. This is not persistent MSBuild execution or
a default change. Logs: `/tmp/graph-roadmap-linux-worker.log`,
`/tmp/graph-roadmap-linux-worker-tools.log`, and
`/tmp/graph-roadmap-linux-worker-restore.log`.


### Worker capacity and benchmark controls

The worker's configurable `worker_cache_mb` defaults to 4096 MiB of logical
snapshot storage, counting shared aliases. It clears excess cache state between
requests; it is not a hard active-request disk quota. Zero disables retention.
Both default and zero-budget controls pass body edits, failure recovery,
configuration changes and fresh native parity on Linux/Bazel 9.2.

`upstream_edits.py --expected-misses N` rejects a timing sample whose miss count
differs, while restoring its source edit. The first fresh prepared-Restore series
found all 202 snapshots because its edits had already been measured in the
normal-Restore series. Those samples are excluded from body-edit timing; the run
was interrupted and the source restored. A corrected series uses distinct edits
and requires one miss. Reports for the discarded run remain in
`/tmp/graph-roadmap-fresh-prepared-timing`.

### Expanded Linux correctness checkpoint

Nineteen focused graph fixtures pass on Linux ARM64: replay and integrity,
reference roles and reviewed dependencies, configurations, Framework references,
packages/package SDKs, signing, Web/Razor, analyzers, native tools, MTP/VSTest,
shared outputs, prepared Restore, directory inputs and evaluation refresh.
The Framework fixture needed its existing pinned packages supplied explicitly;
the native fixture needed GCC/libc headers installed in the qualification VM.
The evaluation probe's source list was updated for the shared worker helper.
Reports and prerequisite versions are preserved in
`/tmp/graph-roadmap-linux-qualification`.

Worker Publish reuses two projects and rebuilds one after a dependency body
edit, executes the changed implementation and matches the fresh native control's
compared outputs. Native generator data/binary/mode controls pass through the
worker. For both MTP and VSTest, a dependency body edit leaves its reference
assembly byte-identical and the test project compiled from cache (one hit/one
miss), yet reruns the tests and observes the changed implementation. Restoring
the body passes again. Fresh graph actions also invalidate the test result, but
without a remote endpoint they rebuild both projects from an empty local cache.
Logs: `/tmp/graph-roadmap-linux-expanded-worker.log` and
`/tmp/graph-roadmap-linux-protocols-body.log`. These remain synthetic controls;
they do not qualify all upstream test or Publish targets.

### Skip inactive design-time item evaluation

Expanded Avalonia SimpleTheme qualification exposed a stall during `Project`
evaluation: the API's default IDE behavior expands items even when their
conditions are false. Disabled platform globs consequently enumerated the host
filesystem root. A bounded original run exceeded 60 seconds; a diagnostic
filesystem trace identified the enumeration. The CLI root-wildcard environment
guard alone did not prevent it.

Graph sync and graph build now use
`ProjectLoadSettings.DoNotEvaluateElementsWithFalseCondition`, retaining active
build evaluation without collecting IDE-only inactive items. See the
[MSBuild API contract](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.projectloadsettings).
`sync.py` and `evaluation_reuse.py` pass false-condition expressions that
previously failed, reject those same expressions when activated, and retain
build/replay, new-glob, import and mutation-refresh checks. SimpleTheme sync now
reaches its next explicit document-contract rejection in 4.30 seconds including
offline Restore. That is a qualification unblock, not a completed build or a
representative performance benchmark. Expanded task/resource bindings remain open.

### Corrected fresh-package preparation comparison

The corrected three-sample Orchard series used distinct body edits and
`--package-state fresh --expected-misses 1`. Every sample hit 201 projects and
rebuilt one. Median prepared recovery was **35.75 s**, versus **13.49 s** warm
raw graph MSBuild (raw excludes Restore). Phase medians were application of
preparation 14.45 s, evaluation 3.76 s, input hashing 2.20 s, execution 4.34 s
and final verification 10.90 s. File sets matched; all samples retained the
898 previously explained generator-dependent differences.

This is slower than the ordinary fresh-package series (23.27 s). Both series
used the frozen evaluation-sharing runner; this does not measure the later
inactive-item fix or persistent broker. Preparation creation is excluded from
recovery and was not separately scored because its earlier run overlapped
checks. Reports: `/tmp/graph-roadmap-fresh-prepared-corrected`. The correction
replaces the discarded zero-miss series, not the existing conservative default.
A prepared artifact alone is not a performance win: a verified, worker-owned,
read-only package tree is the next candidate for avoiding repeated copying and
verification. It is not yet implemented or qualified.

### Independent sandboxed worker recovery

The updated public worker path passes independent producer/consumer qualification
with `linux_bazel_remote.py --graph-worker --spawn-strategy linux-sandbox`.
The Bazel 8.8 producer built three projects in `runtime-rbe`; that VM was then
stopped. A fresh four-CPU/four-GiB Apple VM, with a different repository/SDK path
and empty local project/action caches, used Bazel 9.2 to recover three HTTP-cache
hits and then two hits/one miss after a dependency body edit. Both executables
returned the expected values. Both bootstraps produced runner SHA-256
`3659081d9f9f9ec4314fa0af64cf2739c7bfcac84f755adf3d5f0c5d6fb473d0`.

Both builds enabled `--worker_sandboxing`; nonworker actions used native
`linux-sandbox` and graph requests retained the nested stable-path sandbox.
Only declared source/SDK/tool inputs were copied to the consumer. No producer
workspace, NuGet directory, project snapshots or Bazel output base was shared.
The independent HTTP cache remained available. Logs are
`/tmp/graph-roadmap-independent-worker-{producer,consumer}.log`.
This qualifies small ARM64 worker recovery, not an upstream graph or RBE.

### Graph-wide package versions

The expanded Avalonia public action requires several versions of some NuGet
packages across its configured projects. `msbuild_package_lock` now accepts
`allow_multiple_versions = True` for a graph-wide pinned inventory. Default
locks and individual project consumers still require one version per ID;
conflicting declarations of the same ID/version remain errors.

The public `devex.py` fixture builds two independent apps with Api/Core 1.0.0
and 2.0.0 in one graph, checks their separate Restore assets and runtime values,
and then upgrades the first app. Existing package-hash, incomplete-closure,
configuration and task-input controls also pass. All 47 native Bazel analysis
tests and `scripts/check.sh` pass on macOS ARM64/Bazel 9.2. This transfers a
required input contract; expanded Avalonia build/worker parity is still separate.

### Expanded Avalonia worker qualification

SimpleTheme at Avalonia `37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`
now passes public graph execution with its reviewed source generator, build tasks
and XAML resources. The inventory has 81 pinned package versions; the graph has
11 physical projects, 29 configured nodes and 23 compiled nodes, including
upstream net6.0/netstandard2.0 configurations. No upstream-specific production
inputs or skipped legacy targets were added.

On Linux ARM64/Bazel 9.2, a restarted consumer with no local project snapshots
recovered all 23 projects from HTTP cache with identical compared bytes and
modes. XAML editing reused 22 projects and rebuilt one; the executable inspector
observed two styles instead of one. Body/API edits each reused seven and rebuilt
16; the generator edit reused five and rebuilt 18. Each edited worker result
matched a fresh native sandbox control's compared outputs, including file sets
and modes. `.AssemblyReference.cache` remains excluded as in other comparisons.
These are correctness checks, not paired raw-MSBuild performance measurements.

Run `upstream/avalonia_worker.py WORKSPACE RESULTS --output-base PATH` against
the generated disposable SimpleTheme graph. `--seed-evidence` accepts a saved
producer manifest; `--only` selects a scenario for independent reruns.
Reports are preserved in `/tmp/graph-roadmap-avalonia-linux-evidence`. The first
run exhausted host disk during the tool case; no result from that interrupted
case is counted. Its reports were preserved, obsolete benchmark payloads removed,
unused VM blocks trimmed, and all source edits restored before the tool case
passed separately. Tests, native deployment and full Avalonia application scope
remain unqualified by this slice.
