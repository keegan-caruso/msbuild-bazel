# Graph cache performance and qualification plan

## Objective

Qualify the graph-cache backend on dotnet/runtime, then build a selected runtime
from source and use it to run an ordinary app. Incremental body/API edits and
fresh remote-cache consumers are the primary cases. Orchard and Avalonia results
remain historical evidence; further expansion of those workloads is deferred.

The graph-cache path remains the primary development direction. Keep MSBuild
evaluation, SDK targets and project scheduling. Bazel declares
sources, packages, tools, configuration and outputs. Changes must remain generic;
upstream-specific declarations belong in qualification mappings. Keep graph mode
opt-in until correctness, capability and performance gates pass.

Start with runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`),
SDK 10.0.400 and Linux ARM64. Qualify both Bazel 8.8.0 and 9.2.0. The existing
30-project Pipelines graph result is macOS ARM64; its mapping must be evaluated
for Linux, not copied with `TargetOS=osx`. Older per-project native/app results
are useful contracts to transfer, not evidence for the graph backend.

## Execution rules

For each change: small correctness fixture, larger measurement, review, commit.
Push validated checkpoints. Record failed checks and remaining gates honestly.
Use pinned tools and upstream revisions. CI remains manual-only. Do not weaken
input verification or hide output differences to meet timing targets.

## Ordered work

1. **Pipelines on Linux.** Reproduce the generated managed graph with explicit
   Linux properties, offline packages, task-host SDK inputs, API validation and
   per-file shared-binplace ownership. Compare cold builds and complete replay
   outputs with the equivalent raw upstream command. Check native sandbox and
   sandboxed workers before relying on worker timings.
2. **Paired incremental baseline.** Capture three paired samples for no-op,
   implementation-body and public-contract edits. Runtime separates reference
   and implementation projects: edit the producer that actually owns each role.
   Require the expected hits, compiler calls, reference bytes and runtime copies.
   Include a test consumer using an implementation reference; a body edit may
   legitimately recompile that consumer. Compare ordinary and prepared Restore,
   including the read-only worker packages candidate.
3. **Larger managed scope and edit matrix.** Inventory configured nodes and
   expand from Pipelines through selected library/test roots toward the existing
   281-managed-action qualification. Compare equivalent roots/frameworks rather
   than assuming those action counts transfer to graph mode. Cover leaf and
   shared body/API edits, propagation stopping at unchanged consumer contracts,
   friend assemblies, generators, resources, packages and configuration changes.
   Do not prune authored frameworks just to improve a comparison.
4. **Remove measured overhead.** Profile the larger scope before choosing work.
   Measure evaluation, Restore/preparation, SDK/package hashing, transfers,
   materialization, compilation and final verification. Prioritize repeated work
   that can be removed: verified immutable preparation, SDK identity reuse and
   immutable evaluated information with complete invalidation keys. Reuse Restore
   on body edits; changed packages, imports, globs, RID/configuration, SDK/tools
   and executable modes must invalidate the appropriate preparation. Never retain
   target-mutated project instances. Measure COW and retained outputs before
   changing their defaults; smaller fixtures found little wall-time benefit.
5. **Upstream test execution.** Transfer the selected eight-suite qualification
   using runtime's actual test harness and source-built host. Preserve
   implementation references, test names/outcomes and deliberate failure checks.
   Dependency body edits must refresh runtime files and invalidate test results
   even when test compilation is cached. Report build and test times separately.
6. **Native construction and app.** Declare native sources, generators,
   compiler/build tools, headers, sysroot and configuration. Preserve upstream
   CMake/Ninja or make behavior through declared producers; the managed graph
   alone does not build native components. Compose the selected source-built
   CoreCLR/JIT, CoreLib, libraries and host into the existing runtime provider.
   Run an ordinary app without the installed runtime or build checkout and
   verify loaded binaries against their producers. Missing CoreCLR must fail.
   Exercise native source/header/tool changes and managed library/app edits.
7. **Independent recovery and faults.** At managed and runnable-runtime
   milestones, stop the producer and use an independent Linux consumer with
   empty local caches and a different external workspace path. Verify declared
   stable internal paths, exact files/bytes/modes and runtime/test outcomes;
   measure SDK/package acquisition separately. Exercise corruption, eviction,
   conflicts, concurrent writers and interruption. Repeat public Bazel 8.8/9.2
   native-sandbox and worker checks. ARM64 evidence does not qualify x86-64 or RBE.
8. **Readiness, then broader integration.** Review correctness, paired timings,
   transfer volume, disk and peak memory before switching defaults. Proposed
   targets remain warm edits within about 20% of equivalent raw MSBuild and fresh
   recovery clearly faster than rebuilding. These are targets, not results.
   Qualify the runtime/app milestone first; full runtime tests, other platforms,
   source-built SDK and source-built Native AOT are later expansions. SDK source
   construction is a separate integration, not something the runtime managed
   graph proves. Remove the old compilation backend only after parity qualifies.

## First execution checkpoint

Implement and commit these bounded pieces before expanding the runtime scope:

1. **Linux contract fixture.** Add reviewed Linux ARM64 mappings and shared
   binplace outputs for `System.IO.Pipelines/src`, then its test project. Reuse
   the generic sync and replay machinery; do not put runtime-specific behavior
   into production rules. Record every configured node and required bootstrap
   input. Pass Build, full local replay and worker/native-action parity on both
   Bazel baselines. Use fresh raw builds for parity controls; do not score them
   as ordinary incremental builds.
2. **Runtime edit fixture.** Add unique body and public-contract mutations plus
   restoration checks. Assert expected compilation, reference hashes and current
   implementation copies. Include the authored implementation-reference test
   consumer. Fail on extra rebuilds or an unchanged implementation after an edit.
   Do not hardcode the earlier macOS graph's project count for Linux.
3. **Paired Linux scorecard.** Extend the existing edit harness to invoke public
   Bazel graph actions and collect full wall time, worker preparation, runner
   phases and raw graph-mode commands. It currently measures the standalone
   runner, not full Bazel. Preserve diagnostic standalone rows separately.
   Report ordinary Restore and prepared read-only worker packages as separate
   candidates, not an assumed improvement. Commit the compact measured summary.
4. **Choose the next change from the profile.** Expand the same fixture using
   the selected roots in `tests/explicit_msbuild/runtime/subset_slices.json`:
   collections, threading, filesystem, sockets, then loaded-library/shim roots
   and Pipelines tests. Check each expansion before combining it. Profile the
   larger graph and select the largest removable repeated cost. Commit each
   optimization after its synthetic invalidation controls and paired upstream
   measurements pass. Keep or revert it according to wall-time benefit and cost.

The first checkpoint is complete when the Linux contract and edit controls pass
and the scorecard has comparable graph/raw no-op, body, API and cold rows, plus
local/remote recovery rows. Capability failures remain work items; they must not
be converted into omitted inputs, disabled validation or reduced upstream scope.

## Measurement contract

Start with one 4-CPU/8-GiB Linux ARM64 build VM and four MSBuild nodes, matching the
current runner's fixed `MaxNodeCount=4` and edit harness's raw `-m:4`. Use one graph
worker and a 4096-MB worker-cache budget; record that the budget does not cap all
process memory. Check host headroom and prevent other build VMs/jobs from
competing during a scored run. Stop the producer before the independent consumer
runs. If the scope exceeds the VM budget, choose a new matched configuration and
rerun the paired baseline rather than comparing unlike resource settings.

Hold compiler reuse, architecture, configuration, entry points and frameworks
fixed within each pair. Start with shared compilation disabled on both sides,
matching the existing harness; qualify compiler reuse as a separate candidate.
Use raw graph-mode MSBuild with the same configured roots. Show normal raw
MSBuild separately if desired; do not silently substitute it in a graph comparison.

| Case | Graph state | Raw comparison |
| --- | --- | --- |
| Warm no-op | Same inputs and warm Bazel server; whole graph action may hit | Warm outputs; no Restore |
| Body edit | Unique implementation edit; graph executes with project-cache reuse | Same edit and warm outputs; no Restore |
| API edit | Unique authored public contract/source edit; graph executes | Same edit and warm outputs; no Restore |
| Fresh local recovery | Fresh outputs; local project snapshots retained | Clean compilation with available SDK/packages |
| Fresh remote recovery | Independent consumer; empty local snapshots and outputs | Clean compilation in the same consumer configuration |
| Cold build | Fresh outputs and empty build caches; available SDK/package archives | Clean outputs; separately measured Restore and Build |

For no-op/body/API, capture three pairs and report medians and ranges. Use unique
edits and alternate graph/raw order to reduce cache-warmth bias. Also collect
three local-recovery samples; repeat independent remote and cold cases where
practical, and label any single observation. Restore sources and verify original
outputs after each series. Profile diagnostic runs separately; leave profiling
off in scored runs unless its measured overhead is negligible and applied equally.

Report complete Bazel wall time and runner phases. Include worker broker
preparation/materialization in the total; concurrent operation sums are not wall
segments. Record raw Restore separately and show total workflow cost as well.
Distinguish warm raw outputs from fresh graph outputs. Record hits/misses,
compiler calls, output parity, bytes/files hashed/copied/transferred, and peak
process/VM memory. Source acquisition, initial sync, SDK/package downloads,
native build, host composition and test execution each get separate measurements.
Separate whole-graph Bazel action-cache hits from project-cache hits. Include a
unique edited remote consumer that must execute the graph and recover unchanged
projects; an unchanged whole-action hit does not qualify project-level replay.

Proposed acceptance: body/API medians within about 20% of equivalent raw build
and fresh recovery clearly faster than clean rebuilding. Preserve the earlier
per-project edit results as a secondary baseline on matched scopes. Cold may be
slower, but report both Build-only and Restore-plus-Build ratios and review the
regression before expanding or switching defaults. Do not declare success from
hit counts alone. Record raw commands, candidate revision, pins and limits with
compact summaries; keep large logs/binlogs outside Git.

## Status

The generic optimizations already implemented are retained. The next work is
runtime qualification and measurement, not repeating completed synthetic work.

| Step | Current evidence | Remaining gate |
| --- | --- | --- |
| 1. Linux Pipelines | Implementation and test Build/replay/native parity pass on Linux ARM64, Bazel 8.8/9.2; 819/998 snapshot files | Broader runtime contracts |
| 2. Incremental baseline | Public Linux worker body/API/no-op medians and six/eleven compiler-call parity pass | Prepared Restore comparison and independent recovery |
| 3. Larger scope | Per-project backend qualifies selected suites and 281 managed actions | Graph contracts and invalidation across the expanded scope |
| 4. Removed work | Shared CAS, ownership/path reuse, shared evaluation context and read-only worker packages | Runtime phase profile; safe cross-request SDK/evaluation reuse and large-worker timing |
| 5. Tests | Older source-only host: 118,952 passes / 64 skips | Graph-backed test builds/execution, source host and edit invalidation |
| 6. Native/app | Per-project source-built app and native inputs qualified | Transfer native producers and host composition; app runs on graph-produced outputs |
| 7. Recovery | Small independent ARM64 workers, native sandbox and fault controls pass | Runtime managed/native/app recovery and timings on independent consumers |
| 8. Readiness | Graph mode remains opt-in | Runtime capability/performance gates; later SDK/AOT/full-repository expansion |

The worker still starts a fresh MSBuild child per request. Read-only preparation
avoids package copying and final package rehash, but each child still validates
SDK/package bytes. No large-runtime timing establishes the benefit yet.
The completed disk cleanup removed older qualification containers after preserving
compact reports; recreate only the workers needed for the selected milestone.

## Partial replay checkpoint

The paired Linux test-graph body edit exposed an initial-target replay bug.
Snapshots retained explicitly requested results but omitted
`ProjectInstance.InitialTargets`. Runtime's `ValidateTargetOSLowercase` therefore
made nested MSBuild requests unsatisfied after cache hits. The diagnostic binlog
showed cached linker/reference projects recompiling and a cached generator
executing translation tasks. The failed body run is excluded from timings.

Snapshots now retain initial-target results alongside requested results, without
duplicates. Skipped initial targets count as completed under the same input and
dependency fingerprint. Changed validation imports or conditions still invalidate
those results. No project state is retained between MSBuild requests.

On the pinned Linux ARM64 SDK, `initial_targets.py` reproduces the old failure,
then passes cold Build, complete replay, consumer-only body replay, changed
validation inputs and a changed condition that deliberately fails. The ordinary
three-project replay and source-built analyzer controls pass; owned-code checks
and all 54 ProjectSync tests pass. Reproduce with
`RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/initial_targets.py`
after building GraphBuild. CI was not run.

The corrected runtime body diagnostic gets 32 hits/six misses, exactly six Csc
calls (five implementation frameworks plus the test consumer), and no translation
tasks in cached generators. Its profiled runner time is 22.87 seconds, including
4.75 seconds Restore, 0.71 evaluation, 2.07 input hashing, 14.51 execution and
0.76 final verification. Worker staging adds 0.44 seconds. This single diagnostic
is excluded from the paired scorecard.

## Complete generator inputs

The runtime fixture now declares the 13 checked-in Common/Resources XLIFF files
for LibraryImportGenerator, DownlevelLibraryImportGenerator and
Microsoft.Interop.SourceGeneration. The package discovers these files during
translation targets; they are not ordinary evaluated source items. Each binding
attests the exact owning csproj hash. Production rules have no runtime-specific
logic. Missing declared files fail sync; file edits participate in fingerprints.
Earlier cold builds could synthesize absent XLIFF files from English resources,
so their parity against similarly staged raw inputs was insufficient.

Fresh Linux ARM64 Build/replay/native controls with complete inputs pass on
Bazel 9.2.0 and 8.8.0: 38 misses for each cold build, 38 hits for each complete
replay, and identical 998 snapshot files/bytes/modes. A separate raw graph-mode
Build from the complete upstream source archive matches all 412 persistent
DLL/PDB/resource files byte-for-byte. Both builds use the declared SDK/packages,
four MSBuild nodes and the same internal sandbox paths. Raw output files are
writable; Bazel freezes tree outputs to 0555. No file content was normalized.
SDK PreTrim intermediates are omitted from that compiled-product comparison
because a normal raw no-op removes them; full graph replay/native controls still
compare the complete snapshot scope.

Reproduce with `runtime_prepare.py SOURCE_ARCHIVE PACKAGE_FEED NEW_DIRECTORY
--entry src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`,
then `runtime_qualify.py WORKSPACE NEW_RESULTS --output-base NEW_BASE` under the
pinned Linux ARM64 image. Raw uses `runtime_raw.sh` for matching internal paths.
The qualification harness stops completed Bazel servers to bound VM memory.
These are correctness controls, not scored cold-build medians. CI was not run.
The matched body/API/cold scorecard and independent consumer remain pending.

## Linux implementation checkpoint

The Linux ARM64 Pipelines implementation graph builds through the public Bazel
8.8/9.2 sandboxed workers: 30 configured projects, 86 declared package archives and
108 shared output files. Complete local replay gets 30 hits, and its 819
snapshotted files match fresh native-sandbox builds on both versions, including
modes. The test-consumer graph also passes all controls: 42 configured nodes, 38 compilation nodes and 998 captured output files.

Fresh controls exposed three differing SDK `GenerateResource.cache` files.
These serialize resource-source modification times; the SDK documents their
[optional dependency-cache role](https://learn.microsoft.com/en-us/visualstudio/msbuild/generateresource-task?view=visualstudio).
Implicit snapshots now omit only the expected state file in the evaluated
intermediate directory. Explicit output declarations still take precedence.
Actual resources, satellite assemblies and DLL/PDB outputs remain captured.
A synthetic resource edit changes executed values, regenerates state on a miss,
and replays compiled resources without it. An explicitly owned cache-named file
also survives replay. The remaining 819 files match without normalization.

Reproduce with the commit-addressed runtime source archive (SHA-256
`4fae24371e108a046d7bfd30785e9a2f4400552b165b70300a72f855370da3de`),
the reviewed offline package feed and the pinned Linux SDK:

```sh
python3 tests/graph_build/upstream/runtime_prepare.py SOURCE_TAR_GZ PACKAGE_FEED NEW_DIRECTORY
python3 tests/graph_build/upstream/runtime_qualify.py NEW_DIRECTORY/workspace RESULTS --output-base NEW_BAZEL_BASE
python3 tests/graph_build/resource_state.py
```

Build GraphBuild and ProjectSync first; set `RULES_MSBUILD_DOTNET_ROOT` and the
Bazelisk override for the pinned tools. Preparation validates the source archive,
restores only in disposable sync copies and stages only declared project inputs.
The parity fixture uses an unused declared nonce to force graph execution; its
runs are correctness controls, not performance samples. Owned .NET/style/unit
checks and the existing replay/output-ownership experiments pass. No CI ran.

## Outer-build input correction

The Linux test expansion exposed a language-dependent `Compile` placeholder on
an SDK cross-targeting dispatcher. Sync omits absent compiler placeholders only when
`IsCrossTargetingBuild=true` and no `CoreCompile` target exists. Configured inner
nodes still declare and validate every compiler input. Absent evaluated items
under an outer dispatcher's intermediate directory are also omitted: these are
inner-target output placeholders. Existing outer files remain declared and verified. Missing inner source files and
explicit reviewed task inputs retain their checks. The first public runtime test
build exposed the need to retain existing outer files; that failed run is not
qualification evidence.

`python3 tests/graph_build/sync.py` passes on Linux ARM64, including a two-framework
Build and rejection of a missing inner `Helper.cs`. This qualifies the generic
correction, including an outer intermediate placeholder. The runtime test
contract now synchronizes 42 configured nodes / 38 compilation nodes. Complete
Build/replay and shared-binplace ownership for that expanded graph now pass the
supported-version controls.

## Linux test-consumer checkpoint

The Pipelines test graph compiles all configured dependency frameworks, including
Pipelines net8/net9/netstandard/.NET Framework variants. Five reviewed testing
documents declare the runner template and runsettings template explicitly.
Mobile tool and shell-command items are evaluation metadata for this managed
Linux Build; this does not qualify mobile builds or coverage execution.

A raw graph Build passes with authored-framework Restore and the declared
`NUGET_PACKAGES` directory. Its post-build BinPlace inventory confirms the same
108 explicitly owned shared files. Public worker seed (0/38), replay (38/0) and
fresh native seed (0/38) match all 998 captured files/modes on Bazel 8.8/9.2.
These remain correctness controls, not scored timings or source-host test
execution. Reproduce using `runtime_prepare.py --entry
src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`, then
`runtime_qualify.py` as above. The runner and test-harness contracts are retained;
source-built-host execution remains step 5.

## Public graph diagnostics

`app_graph(..., profile_build=True)` enables runner operation totals and a
`report.binlog` without imported project payloads. Linux worker reports add
staging, child-process, output-verification and cleanup times. Worker totals do
not include Bazel's input staging or the protocol reply; full Bazel wall time
remains the score. Nested/concurrent runner operation totals can overlap.

Profiling defaults to false for ordinary actions, generated facades and prepared
Restore. The public worker controls on Bazel 8.8/9.2 pass default-off checks,
profiled replay with unchanged outputs/hits, failure recovery, property changes
and worker/native Build/Publish parity. Owned .NET checks and pinned Buildifier
checks pass. Scored runs keep profiling off; diagnostic compiler counts and
phase profiles are collected separately.

## Linux Pipelines scorecard

The public graph worker at production revision `129ce14` uses the reviewed
Pipelines test graph: 42 configured nodes / 38 compiled nodes, including all
five authored implementation/reference frameworks. Runtime v10.0.0, SDK
10.0.400, Bazel 9.2.0, Linux ARM64, four CPUs, 8 GiB, four MSBuild nodes,
shared compilation disabled. Prepared Restore and profiling are off.

Three alternating pairs preserve unchanged source timestamps and compare full
Bazel wall time against warm raw graph-mode Build, excluding raw Restore:

| Case | Graph median (range) | Raw median (range) | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.169 s (0.154–0.236) | 1.945 s (1.883–2.077) | Whole graph action hit |
| Body | 23.318 s (22.355–26.009) | 17.281 s (15.572–17.387) | 32 hits / six rebuilds |
| API | 27.912 s (27.593–29.092) | 21.058 s (20.800–21.961) | 27 hits / eleven rebuilds |
| Fresh local outputs | 9.669 s | Not paired with warm raw | 38 project hits; three forced graph actions |
| Cold compilation (one observation) | 114.088 s | 95.912 s Build + 1.638 s Restore | Zero hits / 38 rebuilds |

Body/API are about 35%/33% slower than raw; the 20% target is not met.
Cold has available SDK/packages, fresh outputs, empty project snapshots and
warm Bazel repository/bootstrap state. It is about 19% above raw Build alone
and 17% above Restore-plus-Build; acquisition is a separate setup cost.
Each pair matches 412 persistent DLL/PDB/resource files byte for byte. Body
changes implementation bytes and retains reference bytes; API changes both.
The authored test consumer uses implementation references and must rebuild on
body edits. Separate profiled binlogs confirm exactly six/eleven compiler calls
for both engines. Bazel freezes tree-artifact modes to 0555; raw leaves 0644.
Full worker/native correctness controls still compare all 998 snapshot files
and modes across Bazel 8.8/9.2. Twenty PreTrim intermediates removed by ordinary
raw no-op targets are excluded only from the persistent-product scorecard.

Raw uses `runtime_raw.sh` for the same stable SDK/workspace namespace, because
ILLink embeds intermediate PDB paths beyond compiler PathMap. No output bytes
are normalized. These timings exclude acquisition/sync and bootstrap setup.
At 250 ms sampling, scored VM memory used peaks near 1.90 GiB with at least
5.98 GiB available; this is VM availability, not summed process RSS.

The separate body diagnostic spends 4.12 s on Restore, 0.73 s evaluation,
1.84 s initial hashing, 14.27 s execution and 0.80 s final verification.
Worker staging is 0.51 s. Cumulative hashing reads 3.93 GB in 25,156 calls;
operation totals overlap and are not additional wall segments. This points to
repeated Restore and immutable SDK/package verification as candidates, rather
than extra compilation. Prepared read-only packages remain unmeasured here.

That candidate exposed a generic package-SDK preparation bug: bootstrap selected
`NUGET_PACKAGES` after the environment had been fingerprinted. The runner now
selects its owned `.nuget` root before Create/Apply; environment validation remains
complete. `package_sdks.py --prepared-restore` reproduces the failure before the
fix and passes preparation/body reuse, authored NuGet.Config preservation and
missing-archive rejection afterward. `prepared_restore.py` also passes
input/package/config/environment invalidation, corruption and relocation controls.
Owned .NET checks, including 54 ProjectSync tests, pass on Linux ARM64.

`runtime_prepare.py --prepared-restore` now generates the separate Restore
contract for every configured node. The prepared Pipelines fixture passes seed
(0/38), replay (38/0) and native (0/38) with all 998 files/bytes/modes matching
across Bazel 8.8/9.2. Workers use read-only prepared packages; native rules copy
them into the owned workspace. The qualifier now sets `linux_worker=False` for
native controls, since changing only Bazel's strategy still invokes the worker
adapter for a single request. Timed candidate comparison is the remaining gate.

Reproduce after `runtime_prepare.py ... --entry
src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj`:

```sh
python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE --samples 3 --diagnostics
python3 tests/graph_build/upstream/runtime_cold.py WORKSPACE NEW_RESULTS \
  --output-base NEW_BASE
```

Use the pinned Linux image and tool overrides from the preparation checkpoint.
The first comparison accidentally rewrote an unchanged reference source and
made raw compile five extra projects. It and incomplete/mismatched-path runs
are excluded. Only the corrected complete series above is scored. Large logs,
binlogs and memory samples stay in disposable results; older per-project and
macOS probes remain in [performance](performance.md#runtime-backend-comparison).

## Historical report summary

These Orchard/Avalonia results explain completed work; they are not the remaining
upstream acceptance plan or a prediction of runtime timings.

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

Retained roadmap logs and comparisons live under `/tmp/graph-roadmap-*` on the
qualification host. Cleanup preserved compact older outcomes under the ignored
`artifacts/disk-cleanup-20260930/` directory. Neither is a durable public artifact.
This summary preserves the conclusions, rejected runs and limits;
[performance](performance.md#current-graph-cache-optimization-checkpoint) is the
short timing scorecard. The status table above lists the remaining work.
