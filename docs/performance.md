# Performance

No-op builds, method-body edits and remote-cache recovery are the strongest
measured cases. **Cold builds and larger-graph API edits remain the main gaps.**
Body and API edits are the primary scorecard; there is no single overall speedup.
The latest [runtime qualification](#runtime-qualification-closure) separates
matched cold builds, incremental edits and independent project recovery.

These results come from pinned workloads; they do not measure every commit on
main. Linked reports contain the commands, samples and raw evidence. The
runtime results include a later baseline with compiler reuse.

A later audit found that the host has 16 GiB RAM, while some historical runtime
experiments allocated a 16 GiB build VM alongside other VMs. Treat those elapsed
times as observations subject to host memory pressure. The
[follow-up qualification](runtime-cold-timing.md#compiler-attribution-and-retained-memory)
separates diagnostic runs from a single, memory-budgeted build VM.

## Generic graph-cache runner

The opt-in [generic graph runner](project-cache-migration.md#generic-edit-timing)
previously measured **6.88/6.93 s body** and **7.37/7.21 s API** (runner/raw) on a
128-project synthetic chain, with three paired samples. Removing repeated
transitive output scans roughly halved the runner's edit time. These measurements
include process startup, evaluation and local snapshots, but exclude Bazel,
Restore and remote transfers. They do not establish Orchard/runtime parity or
justify changing the default yet.

For newly generated contracts, qualified reference boundaries reduced a separate
32-project chain from **16.51 to 2.13 s body** and **16.67 to 2.60 s API**;
paired raw MSBuild measured **2.10/2.62 s**. Body edits now hit 31 projects and
rebuild one. These medians use three samples, disabled transitive compiler
references, and a stable standalone workspace. An explicit COW experiment on the
128-project chain reduced body time only from **7.03 to 6.74 s**; the default
.NET copy path remains unchanged. See [measurements and qualification](project-cache-migration.md#copy-on-write-measurement).

## Runtime backend comparison

The remaining [graph-cache plan](graph-cache-plan.md) now focuses on
**dotnet/runtime**. Existing fast Linux edit results belong to the per-project
backend; they do not establish performance for its graph-cache replacement.

| Backend / scope | Case | Ours | Raw MSBuild |
| --- | --- | ---: | ---: |
| Per-project, Linux managed runtime scope | Pipelines body edit | 2.081 s | 11.576 s |
| Per-project, same scope | Pipelines API edit | 7.970 s | 13.945 s |
| Per-project, memory-budgeted Linux runtime scope | Cold compilation | 301.83 s | 139.75 s |
| Test-only graph probe, macOS Pipelines implementation | Body edit | 4.561 s | 4.360 s |
| Generic graph runner, macOS Pipelines implementation | Full local replay | 9.50 s | Not paired |

The edit medians are three samples: **5.56x faster body / 1.75x faster API**.
Cold is one candidate and remains **2.16x raw build time**; raw Restore adds
72.69 s separately. These Linux measurements cover managed builds, excluding
native construction, host composition and test execution. Their scope and
resource settings are detailed [below](#latest-compiler-and-memory-qualification)
and in [runtime timing](runtime-cold-timing.md).

The [probe](runtime-project-cache-probe.md) edit numbers are single runs on a
smaller managed graph, not production rule benchmarks. Generic replay has
30 configured hits and includes offline Restore and input validation; see
[its scope](project-cache-migration.md#runtime-contract-qualification).
Its concurrent 114.77 s cold run is not a scored benchmark. These different
workloads are not an optimization series.

### Public Linux graph worker

The prepared-Restore Pipelines test slice retains all authored frameworks and
38 compiled nodes. Three-sample full Bazel wall-time medians:

| Case | Prepared graph worker | Paired raw graph MSBuild | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.122 s | 1.811 s | Whole graph action hit |
| Body edit | 17.823 s | 14.846 s | 32 projects hit / six rebuilt |
| API edit | 22.124 s | 22.125 s | 27 hit / eleven rebuilt |
| Fresh local outputs | 4.023 s | Not paired with warm raw | 38 project hits |

Linux ARM64, four CPUs/8 GiB, SDK 10.0.400, Bazel 9.2.0, four MSBuild nodes,
shared compilation and profiling off. Raw retains warm outputs and excludes
Restore; the graph includes preparation application and all worker overhead.
All pairs match 412 DLL/PDB/resource byte inventories. Separate diagnostics
confirm the same six/eleven compiler calls on both sides. Body edits rebuild
the authored implementation-reference test consumer.

Body overhead is about 20%; API is effectively equal to raw. A separate body
profile spends 1.87 s applying preparation, 0.39 s initial hashing and 0.10 s
final verification. Read-only prepared packages remove copying and the final
package rehash; SDK/package validation remains. The earlier ordinary-Restore
series measured body 23.318 s versus 17.281 s raw, API 27.912 s versus
21.058 s, and recovery 9.669 s. Raw timings also vary; assess each candidate
against its paired control rather than attributing the entire reduction to code.

One ordinary-Restore cold observation is 114.088 s versus 95.912 s raw Build
plus 1.638 s Restore (about 17% overhead), with SDK/packages and Bazel bootstrap
already available. The first prepared cold observation regresses to 184.683 s
versus raw 106.393 s Build plus 1.635 s Restore (about 71% workflow overhead).
Two later unprofiled controls are 129.473 s versus 110.543 s raw workflow
(preparation executed), and 126.612 s versus 109.106 s (preparation cached).
These are about 17%/16% overhead; differing preparation states and substantial
variation prevent a combined median. The original slow observation is retained.
The diagnostic is excluded from scored timings.
Prepared Restore remains opt-in; larger graphs and native/runtime-host
qualification are still open. See the
[scorecard, ranges and reproduction](graph-cache-plan.md#linux-pipelines-scorecard).

Independent ARM64 HTTP recovery now reuses all 38 projects with 998 exact files:
21.383 s median (18.434–22.675; three fresh consumer bases). Clean raw Restore +
Build in the same consumer takes 105.999 s (one control), about five times longer.
A unique remote body/API edit takes 25.980/28.248 s with 32/27 hits; these are
single fresh-output observations, not warm-raw comparisons. A separate diagnostic
fetches 56.8 MB of logical payloads/manifests. See
[independent recovery](graph-cache-plan.md#independent-pipelines-recovery) for
setup exclusions, exact parity and remaining native/test gates.

### Expanded runtime collections graph

The selected Immutable, Collections and LINQ test roots expand to 55 compiled
projects / 61 configured nodes. Three paired samples on the same Linux ARM64
4-CPU/8-GiB configuration, with prepared read-only packages and profiling off:

| Case | Full Bazel worker | Warm raw graph MSBuild | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.153 s | 2.548 s | Whole action hit |
| Immutable body | 24.285 s | 23.615 s | 49 hits / six misses |
| Immutable API | 26.818 s | 29.481 s | 44 hits / eleven misses |
| Fresh local outputs | 4.408 s | Not paired with warm raw | 55 project hits |

Body overhead is about 3%; API is about 9% faster by medians. All 615 compiled
products match raw bytes; separate diagnostics confirm six/eleven compiler calls
on both sides. This is a larger selected build scope, not the complete runtime.
Compilation/execution dominates the 19–24 s profiled runner phases; preparation
and validation still cost 1.4–1.9 s and evaluation about one second. A slow
278.66 s bootstrap/setup observation is retained. Two matched cold controls
measure 179.15 s versus 147.12 s raw workflow (preparation executes), and
165.98 s versus 157.40 s (preparation retained): about 22% / 5% overhead.
Each is one observation with 615 compiled products matching; these states
do not form a combined median. See the [cold controls](graph-cache-plan.md#collections-cold-controls). See [ranges, commands and limits](graph-cache-plan.md#collections-incremental-scorecard).

### Loaded-common runtime graph

The reviewed graph retains **182 configurations / 163 compilations**. Three
paired Linux ARM64 samples with SDK 10.0.400, Bazel 9.2.0, four CPUs/8 GiB, four
MSBuild nodes and prepared read-only packages:

| Case | Full Bazel worker | Warm raw graph MSBuild | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.192 s | 5.564 s | Whole-action hit |
| Pipelines body | 18.793 s | 18.904 s | 158 hits / five misses |
| Pipelines authored API | 36.576 s | 33.531 s | 147 hits / sixteen misses |
| Fresh local outputs | 7.547 s | Not paired with warm raw | 163 project hits |

Body time is effectively equal; API overhead is about 9%. All 1,447 compiled
products match raw bytes. Separate binlogs confirm identical five/sixteen compiler
calls. Preparation validation takes 1.7–2.1 s and evaluation about 2.3 s; SDK
execution dominates. This does not qualify a complete runtime, independent
recovery or source-host tests. See [ranges, phases and reproduction](graph-cache-plan.md#loaded-common-incremental-scorecard).

### Expanded source-host runtime graph

The qualified combined graph has **260 projects / 543 configurations / 481
compilations**. Linux ARM64, SDK 10.0.400, Bazel 9.2.0, four CPUs/8 GiB, four
MSBuild nodes and one graph worker. Prepared packages are read-only; the fixture
explicitly uses an 8192 MiB logical disk-cache budget. Profiling and shared
compilation are off for the scored rows. No other build job runs concurrently.

Three alternating raw/graph pairs measure `//:graph`, excluding test execution:

| Case | Full Bazel wall median (range) | Warm raw graph MSBuild median (range) | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.575 s (0.250–1.154) | 17.991 s (17.723–18.603) | Whole-action hit |
| Pipelines body | 37.839 s (37.147–39.538) | 30.443 s (29.876–34.274) | 475 hits / six compilations |
| Authored Pipelines API | 53.369 s (52.652–54.230) | 46.774 s (45.972–46.913) | 464 hits / 17 compilations |
| Fresh local outputs | 24.543 s (22.800–29.064) | Not a warm-raw comparison | 481 hits |

Body overhead is **24%**, slightly beyond the proposed ~20% gate; API overhead is
**14%**. All pairs match all **3,622 compiled DLL/PDB/resource bytes**. Separate
binary logs confirm the same six/17 compiler calls. Source restoration returns
original outputs. The larger graph does not inherit the 163-compilation timing
claim, and there is no new matched cold or remote-recovery median.

The raw baseline is the complete pinned upstream source, previously qualified
against the same graph/SDK/properties/stable paths. It retains warm outputs and
runs no Restore. Graph time includes prepared-input validation and worker costs.
Initial acquisition, sync, native construction, baseline restoration and profiling
preparation are excluded. A startup guard initially compared differently formatted
JSON bytes; parsed contracts were identical. It failed before any timing row.
The successful helper requires the complete parsed contracts to match and records
both document hashes.

Separate profiles are **38.22 s body / 56.19 s API**; they are not scored medians:

| Wall phase | Body | API |
| --- | ---: | ---: |
| Worker staging | 1.15 s | 1.22 s |
| Runner prepared-input validation | 4.91 s | 4.92 s |
| Runner evaluation | 7.50 s | 7.57 s |
| Runner initial input hashing | 2.31 s | 2.55 s |
| SDK execution | 17.29 s | 34.65 s |
| Runner final verification/snapshot | 0.71 s | 0.69 s |
| Worker output verification/cleanup | 0.68 s | 1.34 s |

Within those phases, dependency fingerprinting totals **6.78/9.81 s** across
481 calls. File hashing totals **7.72/11.68 s**, roughly 56,800 hashes / 4.41 GB.
Snapshot validation totals **1.79/5.76 s**. These concurrent operation sums overlap
wall phases; do not add them to the table. Materialization copies roughly
**688/677 MB in 10,621/10,465 copies**, taking **3.29/3.26 s**; no clones occur.
The maximum VM-used-memory estimate across sampled commands, including setup and
diagnostics, is **4.28 GiB**, sampled every 250 ms; it is not process-only memory.

Subsequent preflights below measured fingerprint metadata, immutable preparation
and evaluation reuse. The latest retained change is
[indexed output ownership](#indexed-output-ownership). Graph mode remains opt-in;
this historical scorecard does not imply a default switch.

Reproduce after [full-source and eight-suite qualification](runtime-graph-upstream-tests.md):

```sh
python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE NEW_RESULTS \
  --output-base WARM_BASE --slice runtime-suites \
  --qualified-raw-results QUALIFIED_RAW_RESULTS --samples 3 --diagnostics
```

The helper reuses that owned raw workspace in place and restores its sources and
configuration. It requires the reviewed roots, compilation scope and retained
worker; diagnostic rows follow scored rows. Runner identity starts `714641fc59d3`,
harness `5c6abcb6c9c4`; private summaries retain full hashes and logs. Only compact
findings are committed. Actual 8.8 suite checks, broader edits/native mutations,
independent larger consumers and repeated cold/recovery remain separate gates.

### Node-identity reuse experiment

A request-local configured-node key table passed owned-code checks and six focused
graph controls: input qualification, configurations, reference roles, compiler
references, consumer references and initial-target replay. A separate candidate
seed completed in 1,137 s, including prepared Restore. All 3,622 compiled products
matched the full-source raw control. This is setup, not a matched cold-build result.

The same frozen 481-compilation harness ran three alternating raw/graph pairs:

| Case | Candidate Bazel median (range) | Paired raw median (range) |
| --- | ---: | ---: |
| No-op | 0.352 s (0.346–0.797) | 18.384 s (17.032–18.398) |
| Body | 38.413 s (34.861–38.416) | 31.496 s (31.448–32.892) |
| API | 52.369 s (51.251–53.933) | 45.557 s (45.210–45.686) |
| Local recovery | 22.295 s (21.409–23.702) | Not a warm-raw comparison |

Body/API overhead is **22%/15%**, versus the preceding baseline's **24%/14%**.
The ranges overlap and raw times also changed. This does not establish an
end-to-end improvement, so the production prototype was removed. No-op rows are
whole-action hits; recovery rows force 481 project hits and zero compilations.
Each edit row matches all compiled bytes, with six/17 misses respectively.
Separate diagnostic binary logs confirm six/17 raw and graph compiler calls;
source and configuration restoration passes.

Separate body/API profiles are 42.557/54.295 s. Prepared-input validation is
4.387/4.357 s, evaluation 8.956/7.334 s and initial hashing 2.797/2.613 s.
Dependency-fingerprint operation sums are 9.554/7.606 s and overlap other phases.
They do not establish a consistent improvement either. The experiment uses the
preceding scorecard's hardware, scope and command. Candidate runner SHA starts
`2b28b45be067`; the harness SHA is unchanged. Detailed reports remain private.

### Authored reference lookup preflight

On the evaluated **543-node / 481-compilation** runtime graph, the qualification
raw driver compares the current scan with a per-lookup normalized-path set.
All **29,596 reference classifications** match, including 58 duplicate authored
path groups. Most references already have implementation roles, so the expensive
scan branch is rarely needed. A fresh three-project fixture also checks duplicate
normalized paths with ordinary, `ReferenceOutputAssembly=false`, `OutputItemType`
and `Targets` metadata; all four controls pass.

Five alternating pairs, each averaging 20 passes and including candidate lookup
construction, give **10.507 ms** scan / **5.666 ms** lookup medians per graph.
Ranges are 3.215–11.143 / 1.622–6.739 ms. These are isolated operation costs,
excluding evaluation, output hashing and compilation; they are not full build
timings. The roughly five-millisecond difference does not justify a production
change for the measured multi-second gap. Reference handling remains unchanged.

Reproduce using the complete-source raw workspace and the qualification driver
built from `RuntimeRawGraph.cs.txt` / `RuntimeRawGraph.csproj.txt`:

```sh
bash tests/graph_build/upstream/runtime_raw.sh SDK RAW SCRATCH \
  /__rules_msbuild_graph/output/workspace/.qualification/Raw.dll \
  /__rules_msbuild_graph/output/workspace \
  /__rules_msbuild_graph/output/workspace/graph.generated.json \
  reference-work /__rules_msbuild_graph/output/workspace/.qualification/reference-work.json
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/reference_work.py
```

Use a separate driver copy for the probe; do not replace a scored raw driver or
change the harness during a scored series. SDK/architecture/scope are the same
as the expanded scorecard. No compiler or project-cache action runs in this probe.

### Dependency ordering preflight

The graph cache already memoizes each dependency closure per request. On the
same evaluated runtime graph, an ordered-list prototype preserves all **29,771
configured-node records**, including coordination-node expansion. Only one
compiled consumer in this reviewed contract combines a reference boundary with
transitive compiler references; most lists have no repeated ordering to remove.

Five alternating pairs of 20 passes, including ordered-cache construction, give
**20.843 ms** current / **21.062 ms** cached medians per graph. Ranges are
20.602–63.950 / 20.591–21.153 ms. These costs exclude evaluation, already memoized
closure traversal, output hashing and compilation. There is no measured saving,
so production traversal and ordering remain unchanged.

Fresh chain and diamond controls pass with transitive references enabled and
disabled. A five-configured-node/four-compilation fixture retains both framework
builds and correctly expands the multi-targeting coordinator. All node sequences
match. The metadata controls also pass after the shared qualification-driver change.
Reproduce the preceding probe command with `dependency-order` instead of
`reference-work`; run the small controls with:

```sh
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/dependency_order.py
```

Together, these preflights rule out reference scanning and repeated sorting as
substantial causes of the measured gap in this scope. They do not qualify a
production evaluation cache or predict denser graphs. Prepared-input verification
and project evaluation remain the next measured multi-second targets.

### SDK verification preflight

A Linux ARM64 probe calls the production `ContractFiles.TreeDigest` directly,
without graph evaluation or compilation. The declared SDK 10.0.400 contains
**4,907 files / 671,718,586 bytes**. On the scorecard's four-CPU/eight-GiB worker,
five consecutive hashes have a **0.312 s median** (0.299–0.390 s). This is a
warm isolated measurement, not a cold-build comparison. An earlier first
observation took 1.083 s; JIT/page-cache effects were not isolated.

A new owned copy preserves bytes and executable modes: copying takes **0.331 s**
and verifying the copy **0.348 s**. It also adds about 672 MB per worker.
These are warmed first-use costs; private-copy ownership and request identity
would still need qualification before skipping later verification.

Small controls detect same-size byte edits, executable-mode changes, additions,
renames and removals; restoration returns the original digest. A borrowed
read-only bind mount rejects child writes but exposes an external writer's byte
change. That control deliberately bypasses Bazel input tracking; it is not a
Bazel cache fault or a worker-reuse qualification. The probe builds with warnings
as errors and reports zero warnings/errors.

Bazel 9.2 [compares worker tool digests before reuse](https://github.com/bazelbuild/bazel/blob/9.2.0/src/main/java/com/google/devtools/build/lib/worker/WorkerFactory.java),
and the graph rule already declares the SDK as a tool. That could underpin a
future verified-identity protocol; a read-only path or manifest alone cannot.
The current child receives no such protocol. For this slice, the roughly 0.3-s
warm cost does not justify adding a private SDK cache and its identity/lifecycle
checks. Production verification stays intact. No end-to-end speedup is claimed.
SDK hashing accounts for only a small part of the previous 4.36–4.39-s prepared
phase; prepared-package verification is the next separate measurement.

Reproduce after building `tools/GraphBuild` in Release:

```sh
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/sdk_verification.py \
  NEW_RESULTS_DIRECTORY --sdk DECLARED_SDK --copy
```

The Linux borrowed-mount control requires bubblewrap. Reports and the copied SDK
remain in the disposable results directory; no SDK or machine-specific report is
committed. Restart/concurrency proof remains required for any future reuse cache.

### Prepared-package verification preflight

The runtime payload has **7,678 package files / 1.68 GB** and **1,301 restore
outputs / 73 MB**. Five fresh probe processes call the production hash, path,
restore-key and materialization methods on the scorecard’s four-CPU/eight-GiB
Linux ARM64 VM. Medians and ranges are isolated costs, excluding SDK hashing,
mount-identity checks, restore-output copying, evaluation and compilation:

| Operation | Median | Range |
| --- | ---: | ---: |
| Package bytes | 0.929 s | 0.737–2.193 s |
| Restore-output bytes | 0.048 s | 0.043–0.060 s |
| Source/destination path resolution | 0.047 s | 0.045–0.064 s |
| Mutable restore key | 0.249 s | 0.188–0.389 s |

The existing broker copy-and-verify step takes **2.327 s once** in this observation
(3.210–3.419 s in preceding observations). Reuse takes about **1 ms**. These
first-use observations are not matched cold builds; page-cache state was not
controlled. Staging already reuses its copy. Child package hashing is the remaining
roughly one-second opportunity; these component timings do not account for every
cost in the earlier 4.36–4.39-s full preparation phase.

A small corruption control changes a private copy after materialization. The
cached materializer returns it for unchanged input identity; byte verification
detects the corruption. Production methods also reject different inodes, changed modes, unsupported
manifests, invalid modes and corrupt replacement inputs, with no pending-directory
leak. These injected external writes are outside normal broker operation. Existing
worker controls pass missing-digest fallback, zero-budget eviction and exit cleanup;
Restore controls pass asset/package/configuration/environment invalidation.
The sandbox control now checks read-only package mounts and writable scratch.

A disposable [fs-verity](https://docs.kernel.org/filesystems/fsverity.html) byte-immutability
probe returns **ENOTSUP** on the current filesystem. It does not qualify a worker
identity protocol, even on a filesystem where it succeeds. Keep production byte
verification: neither private ownership, read-only mounts nor an unchanged input
identity detects every private-cache mutation alone. No production fast path or
end-to-end speedup was retained. A future reuse protocol must cover contents,
paths, modes, replacement and worker lifecycle; mutable Restore state stays checked.

Reproduce after building `tools/GraphBuild` in Release, with a preserved prepared
payload (an idle broker's private tree can expire):

```sh
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/package_verification.py \
  NEW_RESULTS --workspace WORKSPACE --contract CONTRACT --sdk DECLARED_SDK \
  --prepared PREPARED_DIRECTORY --samples 5 --materialize
```

The probe builds with warnings as errors and zero warnings/errors. Detailed
reports and the owned copy stay outside Git. No CI or new full-build scorecard ran.

### Runtime evaluation profile

An evaluation-only control uses the qualified **543 configured nodes / 260 project
files / 481 compilations**, SDK 10.0.400 and the four-CPU/eight-GiB Linux ARM64 VM.
It copies only declared inputs and prepared Restore outputs, mounts them read-only
at the graph runner's stable paths, and calls the production `GraphInputs`
constructor. It runs no Restore, targets, compilation or cache replay. Input
hashing still runs, but has its own timer. Input staging, driver setup and
diagnostic serialization are outside the evaluation timer.

One fresh process per mode gives **7.552 s** with profiling disabled,
**7.256 s** with phase timers only, and **15.186 s** with MSBuild's detailed
evaluation profiler. This is a diagnostic control, not a paired build benchmark
or a speedup. The phase-only split is:

| Evaluation work | Wall time |
| --- | ---: |
| Graph construction, including project loading and instance creation | 5.004 s |
| Output-ownership validation | 1.804 s |
| Setup and shared-input existence checks | 0.046 s |
| Configuration selection and Restore-output declarations | 0.090 s |
| Combined input-path validation | 0.135 s |
| Per-node input/reference validation | 0.161 s |
| Ownership index construction | 0.015 s |

Project-load and instance-creation totals are **21.791 / 1.913 aggregate seconds**
across 543 callbacks. They overlap parallel projects and the graph wall timer;
they are not additional elapsed time or CPU measurements. Configuration selection
is a small cost. Ownership validation takes about a quarter of the phase and
currently scans all inputs and other outputs for every output path.

The detailed profiler records **86,720 imports across 859 distinct paths**.
Its aggregate inclusive pass times are properties **24.839 s**, targets
**16.895 s**, items **8.418 s** and lazy items **9.744 s**. These overlap and include
profiling overhead; do not add them to the wall split. The largest located
exclusive totals are `eng/Subsets.props` (**5.233 s**),
`Microsoft.Common.CurrentVersion.targets` (**3.298 s**), SDK bundled versions
(**2.313 s**) and `Directory.Build.props` (**1.946 s**). Repeated imports do not
imply repeated XML parsing: the runner already shares an evaluation context within
each graph pass, and this profile does not isolate parsing from conditional
property/item/target expansion.

All three modes have identical evaluated properties, items and metadata, imports,
references, initial/default target selections, target names and project
fingerprints. All 543 nodes declare initial targets; this probe does not execute
them. Small fixtures also pass cache/output parity, multi-target configuration and
initial-target replay controls. A repaired evaluation-control caller verifies
inactive items, newly present imports, source globs, edited imports and target
mutations refresh between requests.

**Next boundary:** build and validate one request-local ownership plan from the
selected configured declarations and resolved paths. Use an ordered prefix index
to avoid repeated overlap scans, then reuse that plan for ownership lookup.
Keep per-request path, symlink, existence, import and item validation. The plan
must be rebuilt when selected owners, input/output paths, configuration or workspace
root change. File-content hashes and build-time path checks remain independent.
This is planned work with a measured 1.8-s opportunity, not a promised saving.

Keep full project evaluation fresh for now. Source additions/removals change globs;
imports and property functions can inspect files or `Exists()` results; Restore
assets, generated inputs, SDK/package/tool resolution, global properties and the
environment can change evaluation. MSBuild says to discard an
[evaluation context when those inputs change](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.evaluation.context.evaluationcontext?view=msbuild-17-netcore).
Since [property functions can read file contents](https://learn.microsoft.com/en-us/visualstudio/msbuild/property-functions),
source body bytes cannot generically be excluded from an evaluation-cache key.
Never reuse a post-build mutable instance as a pre-build evaluation or skip initial
targets because an earlier request ran them. Cross-request evaluation reuse needs
a separate complete dependency contract and lifecycle proof.

Reproduce after building `tools/GraphBuild` in Release:

```sh
RULES_MSBUILD_DOTNET_ROOT=DECLARED_SDK python3 tests/graph_build/evaluation_profile.py \
  NEW_RESULTS --workspace RETAINED_GRAPH_WORKSPACE --contract CONTRACT \
  --prepared PRESERVED_PREPARED_DIRECTORY
```

The Linux probe requires bubblewrap and pinned SDK 10.0.400. Detailed reports stay
outside Git. An earlier diagnostic that overlapped owned-code checks is excluded
from the timings above. The final control ran after those checks finished.
Standalone runner diagnostics require `RULES_MSBUILD_GRAPH_PROFILE=1`; detailed
MSBuild evaluation additionally requires `RULES_MSBUILD_GRAPH_EVALUATION_PROFILE=1`.
Both are off by default; the Bazel `profile_build` option retains phase-only
profiling. Owned-code and scaffold checks are recorded in the
[qualification plan](graph-cache-plan.md#next-runtime-qualification-slices).
No full build comparison, compiler invocation or new remote-cache qualification ran.

### Indexed output ownership

The request-local ownership plan replaces a scan of every declared input and
other output for each output path. Inputs are sorted once for descendant-range
checks; outputs use owner dictionaries and path ancestors. The same plan answers
ownership lookups. It holds no evaluated MSBuild state across requests. Artifact
reads/writes and final input verification still perform current path checks.

Small controls pass **18 named boundaries and 10,000 generated comparisons**
against the prior quadratic policy, including ownership lookup. Same-owner nested
directories and duplicate declarations remain allowed; cross-owner overlap,
file/directory conflicts and contained inputs retain their previous rules.
A four-project diamond has exact DLL/PDB parity with raw MSBuild for seed, body
and API builds, with four/one/three misses. Configuration, shared-output,
forged-snapshot, input-mutation and worker-restart controls pass. An MSBuild target
that introduces an output symlink after plan creation is rejected at artifact
access; outside bytes remain unchanged.

A separate 543-node evaluation-only observation gives **5.594 s** unprofiled and
**5.421 s** with phase timers. The latter includes **4.984 s** graph construction,
**0.022 s** ownership indexing and **0.006 s** ownership validation. The preceding
observation had 5.004 s graph construction, 0.015 s indexing and 1.804 s validation.
These component observations show the removed scan cost; they are not a paired
whole-build speedup. Detailed profiling remains a separate opt-in control, and
all three candidate modes preserve the same evaluated graph and fingerprints.

The frozen candidate (`4f654d5`) ran the same 481-compilation scope on Linux
ARM64, SDK 10.0.400 and Bazel 9.2.0: four CPUs/8 GiB, four MSBuild nodes, one
worker and the 8192 MiB logical snapshot budget. Shared compilation and profiling
are off in scored rows; no competing build ran.

| Case | Full Bazel wall median (range) | Warm raw graph MSBuild median (range) | Reuse |
| --- | ---: | ---: | --- |
| No-op | 0.343 s (0.307–0.714) | 18.289 s (16.919–18.823) | Whole-action hit |
| Pipelines body | 33.547 s (33.235–33.553) | 32.783 s (28.488–33.173) | 475 hits / six compilations |
| Authored Pipelines API | 51.442 s (47.378–52.189) | 45.421 s (45.136–45.815) | 464 hits / 17 compilations |
| Fresh local outputs | 24.049 s (19.950–25.778) | Not a warm-raw comparison | 481 hits / zero compilations |

These three alternating pairs per case have **2% body / 13% API overhead** by
median. All pairs match the 3,622 DLL/PDB/resource files byte for byte. Raw retains
warm outputs and runs no Restore; graph time includes prepared-input validation
and worker overhead. The separate all-miss seed takes **1,108.335 s**, including
runner bootstrap and prepared Restore; it matches the same compiled products.
This is setup against an already qualified warm raw workspace, not a matched
cold-build comparison.

The historical scorecard measured 37.839/53.369 s for graph body/API builds, but
raw times changed too. These are separate runs, not an alternating old/new
experiment; no overall speedup is attributed to the ownership change. Retain it
for the removed 1.8-s validation scan and improved scaling, with unchanged policy
and passing raw parity. The current edit medians are within the proposed ~20%
gate for this workload; other readiness gates and default selection remain open.

Three forced local recoveries also return exact original compiled bytes, with
481 hits and zero misses. Separate binlogs confirm **six/17 actual compiler
calls on both sides**; these profiled runs are excluded from scored medians.
Their full Bazel times are 37.933 s body / 51.738 s API:

| Wall phase | Body | API |
| --- | ---: | ---: |
| Worker staging | 1.264 s | 0.713 s |
| Runner prepared-input validation | 4.397 s | 3.481 s |
| Runner evaluation | 5.513 s | 5.562 s |
| Runner initial input hashing | 3.027 s | 3.065 s |
| SDK execution | 18.326 s | 32.270 s |
| Runner final verification/snapshot | 0.511 s | 0.557 s |
| Worker output verification/cleanup | 0.281 s | 0.380 s |

Each profile indexes and validates ownership exactly once: indexing costs
0.019/0.014 s, validation 0.003/0.003 s. Graph construction costs 5.277/5.324 s.
Dependency fingerprinting totals 6.297/5.891 s across 481 calls, and file hashing
6.457/7.575 s across about 56,800 hashes / 4.41 GB. These operation sums overlap
wall phases; do not add them. Materialization copies 688/677 MB in
10,621/10,465 copies, with no clones. The maximum sampled VM-used-memory estimate
is 4.98 GiB, including seed and diagnostics; it is not process-only memory.

The new runner requires a fresh all-miss seed before measuring warm runtime
edits. The scorecard now supports `--reseed-worker` with qualified complete-source
raw outputs. It requires zero hits for the seed and records that setup separately.
Default runs still require the retained qualified worker. Scored rows retain exact
compiled-product parity, cache-miss guards, alternating order and separate
compiler diagnostics.

```sh
python3 tests/graph_build/upstream/runtime_benchmark.py WORKSPACE NEW_RESULTS \
  --output-base BASE --slice runtime-suites \
  --qualified-raw-results QUALIFIED_RAW_RESULTS --reseed-worker \
  --samples 3 --diagnostics
```

The full scorecard and logs remain outside Git at
`/qualification/runtime-ownership-scorecard-qualified`; the isolated profile is
`/qualification/runtime-ownership-evaluation-qualified`. Frozen Bazel runner SHA
starts `9118ea2cdbb0`, harness `808ae24ad9a4`. Only compact findings are committed.
The completed helper restores original authored sources/configuration, verifies
original compiled bytes after diagnostics, and stops its worker. Reproduction
requires Linux ARM64, the qualified SDK/packages/native inputs, and the 8192 MiB logical snapshot budget. It does not qualify a new
platform, remote cache or cross-request evaluation cache.

Focused controls, after building the runner and ProjectSync in Release:

```sh
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/output_ownership.py
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/input_integrity.py
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/output_files.py
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/configurations.py
RULES_MSBUILD_DOTNET_ROOT=SDK python3 tests/graph_build/linux_worker.py --bazel-version 9.2.0
```

## Runtime qualification closure

The source-host graph keeps **260 project paths / 543 configured nodes / 481
compilations / 39 roots**, runtime v10.0.0 and SDK 10.0.400. The qualification
runs on Linux ARM64 with four CPUs, 8 GiB, four MSBuild nodes and one graph
worker. The source-identity replay fix is frozen for this final series; its runner
SHA-256 starts `670dcb55f6b1`. Graph mode remains opt-in.

| Boundary | Qualified result |
| --- | --- |
| Bazel 8.8 / 9.2 | Actual eight-suite seed, replay, body/API and failure/recovery controls |
| Managed inputs | Shared source, resource, generated template and imported props; raw byte parity and current runtime observations |
| Native inputs | Independent host source/header/compiler mutations; no managed graph or Restore actions; exact native restoration |
| Independent HTTP consumer | Stopped 8.8 producer, relocated 9.2 consumer, exact 10,780 files/bytes/modes; six/17 misses matching raw compiler calls |
| Cache faults | Missing snapshot/artifact rebuilds; corrupt data and unavailable service fail; exact 481-hit recovery after every case |
| Runtime execution | All eight suites match 118,952 passes / 64 skips and current managed/native producers |

See [commands, failure controls and limits](runtime-graph-upstream-tests.md).
Large JSON, logs, binlogs and test output stay outside Git.

### Repeated HTTP recovery

Three unprofiled recoveries take **34.348 s median (34.271–38.194)**. Each forces
one graph action, uses a fresh broker namespace, has **481 hits / zero misses**,
and restores exact producer files/bytes/modes. Whole-action remote and disk caches
are disabled. The producer is stopped, the workspace is relocated, and repository,
SDK/package and Restore preparation setup is retained. This measures project
recovery with available inputs, not the entire fresh-machine workflow.

The earlier fresh consumer took **109.184 s** with one Restore action, following
separate SDK/package extraction and runner bootstrap. Native construction and
suite execution are also separate. The three-sample series has no Restore
actions and matches full-source raw compiled bytes plus all eight suite outcomes.
Estimated peak VM-used memory is **2.892–2.995 GiB**, sampled from `MemAvailable`
every 0.25 s; it includes OS usage and is not process RSS/PSS.

A separate profiled replay transfers **263,018,617 bytes (250.83 MiB) in 5,680
CAS downloads**, including manifests; action-pointer requests and wire overhead
are excluded. That diagnostic reruns preparation and is excluded from medians.

### Matched cold builds

Three unprofiled pairs alternate raw-first / graph-first / raw-first. Both have
fresh managed outputs; graph requests have empty local project snapshots and no
HTTP project cache. SDK/package inputs, expanded raw packages, the raw driver and
Bazel repository/bootstrap setup are available. Each pair forces one Restore and
one graph action, has **zero hits / 481 misses**, and matches all **3,622** raw
DLL/PDB/resource bytes. This excludes acquisition, native construction and tests.

| Case | Median | Range |
| --- | ---: | ---: |
| Full Bazel workflow | 1,093.530 s | 1,090.422–1,187.811 |
| Raw Restore + Build | 1,048.885 s | 1,022.047–1,086.768 |
| Raw Build only | 967.741 s | 945.796–1,007.308 |
| Raw Restore | 79.460 s | 76.251–81.144 |
| Bazel Restore action span | 87.954 s | 87.300–89.987 |
| Bazel graph action span | 995.484 s | 994.411–1,092.378 |

The ratios of medians are **1.043x Restore + Build / 1.130x Build-only**. The graph
action span includes request staging, MSBuild, verification and snapshot/output
export; it is not a pure compiler timer. Bazel schedules one graph action while
its child uses the same four MSBuild nodes as raw. Other native actions retain
their declared bubblewrap isolation; managed actions use Linux sandboxing and
`worker_sandboxing`.

Peak VM-used estimates are **4.940–5.894 GiB** for graph and **3.399–4.127 GiB**
for raw. The graph-first raw row includes the retained idle Bazel worker. These
are whole-VM estimates from `MemAvailable`, not isolated process memory. No
other build VM or profiler ran alongside the scored series.

Retained-preparation HTTP recovery is about **32x faster** than this cold Bazel
workflow. The earlier fresh-consumer Restore + recovery is also clearly faster
than recompilation, but its acquisition/bootstrap/native/test costs remain separate.

### Refreshed incremental scorecard

Three unique pairs per case alternate raw/graph order, retain warm outputs and
use available Restore preparation. Scored graph actions have profiling off and
no HTTP project cache, whole-action remote cache or disk cache. All pairs match
**3,622** DLL/PDB/resource bytes. No-op rows are whole-action hits; body/API rows
execute the graph with exactly **six/17 misses**.

| Case | Bazel median (range) | Raw median (range) |
| --- | ---: | ---: |
| No-op | 0.407 s (0.403–0.756) | 17.624 s (17.623–18.870) |
| Body edit | 36.640 s (35.976–37.844) | 30.869 s (29.232–31.770) |
| API edit | 52.348 s (49.912–52.724) | 46.910 s (44.351–51.154) |
| Local project recovery | 20.581 s (17.863–25.606) | Fresh-output raw Build is the cold row above |

Body/API overhead is **19%/12%**. Both medians meet the proposed roughly 20%
edit gate for this selected scenario. Local recovery executes one graph action
and restores original bytes with **481 hits / zero misses** each time. Workflow
medians come from complete rows; separate phase medians need not add to them.

These are refreshed baselines, not a causal before/after comparison with the
preceding indexed-ownership series. Shared-source/template/import invalidation
remains conservative. Separate binary logs confirm **six/17 Csc calls in both
engines**, with exact raw byte parity. The body/API diagnostics spend 5.66/5.76 s
in graph evaluation and copy 688.5/677.2 MB across 10,621/10,465 files in 4.28/4.13 s;
no clones occur. Concurrent hashing/replay operation totals overlap these phases
and must not be added as wall time. Scored graph/raw VM-used peaks are 3.790/2.950
GiB; the maximum across setup and diagnostics is 3.843 GiB.

The host disk filled after the scored rows and compiler diagnostics, interrupting
final original-graph restoration and making the consumer filesystem read-only.
Reports were preserved, already-free sparse blocks were trimmed, and the same VM
was restarted. A separate unscored HTTP restoration passes all 10,780 original
files/modes/bytes, raw compiled-byte parity, all eight suites (118,952 passes /
64 skips) and 3,570 current producer-hash observations. The interrupted run and
its recovery are excluded from every timing above; the interrupted controller
itself is not reported as a successful end-to-end run.

### Reproduction and readiness

Use the pinned Linux ARM64 image, SDK/packages/native inputs, reviewed contract,
qualified complete-source raw workspace, four CPUs/8 GiB and the 8192 MiB logical
snapshot budget. The budget is not a memory reservation. See the
[independent-consumer commands](runtime-graph-upstream-tests.md#independent-project-cache-recovery)
for producer/consumer setup. `runtime_remote.py --recovery-samples 3` repeats
recovery with stopped workers and distinct namespaces; `--reuse-consumer-base`
retains repository/Restore setup without retaining project snapshots.

For cold controls, repeat this command with `--sample 1`, `2`, then `3`:

```sh
python3 REPO/tests/graph_build/upstream/runtime_cold.py WORKSPACE PRIOR_SCORECARD \
  --qualified-raw-results RAW_RESULTS --results COLD_RESULTS \
  --output-base BASE --sample 1
```

The final sample may use `--retain-worker`. Restore the original `//:graph`
declaration once with that worker and the same sandbox/cache settings; require
481 hits/zero misses and exclude this setup from scoring. Then run:

```sh
python3 REPO/tests/graph_build/upstream/runtime_benchmark.py WORKSPACE WARM_RESULTS \
  --output-base BASE --slice runtime-suites \
  --qualified-raw-results RAW_RESULTS --samples 3 --diagnostics
```

Without a retained worker, use `--reseed-worker`; its all-miss seed is excluded.
Evidence is in `/qualification/runtime-final-cold`, `runtime-final-warm` and
`runtime-final-recovery` on the independent consumer. The separately completed
restoration is `runtime-final-original-restoration-verified`. The source-identity
fix and runner bytes stay unchanged throughout this series. No CI was run.

Graph mode remains opt-in. These results do not qualify another platform, RBE,
full-repository runtime/SDK/AOT builds or broader native mutation/raw scheduling
parity. Further default-switch work must address the conservative shared-input
costs and qualify the additional supported workloads.

## Current graph-cache optimization checkpoint

Three-sample Orchard body-edit measurements on the roadmap branch retain
201 hits and one rebuild across 202 configured projects:

| Graph package/output state | Runner median | Paired warm raw MSBuild |
| --- | ---: | ---: |
| Retained expanded packages, fresh outputs | 19.18 s | 13.45 s |
| Fresh expanded packages and outputs | 23.27 s | 13.83 s |
| Prepared Restore, fresh packages and outputs | 35.75 s | 13.49 s |

These are standalone local-snapshot recovery timings, not end-to-end Bazel or
remote-cache results. The runner includes Restore/preparation; raw excludes
Restore and retains incremental outputs. They use a frozen runner predating the
later inactive-item fix and worker changes. The final prepared series requires
one miss per sample; the earlier zero-miss series is discarded.

Ownership indexing reduced a controlled warm-filesystem baseline from 25.67 to
21.63 s. Later path/hash and evaluation changes brought the measured retained-
package body result to 19.18 s. COW and retained-output experiments reduced some
copying but did not establish a large wall-time win. Prepared Restore currently
costs more than ordinary Restore on Orchard; it remains opt-in.

Output differences from Orchard's nondeterministic generator are recorded, not
normalized away. A disposable deterministic-generator control matches DLL/PDB
bytes; the two remaining resource-cache differences are SDK apphost timestamp
hashes with unchanged discovered assets. See the
[plan and measured checkpoints](graph-cache-plan.md) for attribution, exact
states, commands and limits. The roughly 20%-overhead target is **not met**.

## Generated graph migration: upstream edits

Single paired runs on macOS ARM64 with SDK 10.0.400, Release, four MSBuild
nodes and shared compilation disabled. Both engines use the same staged
workspace and configuration. Raw MSBuild keeps warm outputs and excludes
Restore. The generic runner removes declared outputs and includes offline
Restore, evaluation, hashing and local snapshot handling. Other qualification
work ran concurrently on this host; use these as migration observations, not
stable benchmark medians or remote-cache timings.

| Scope | Edit | Generic runner | Warm raw graph MSBuild | Hits/misses |
| --- | --- | ---: | ---: | ---: |
| Avalonia.Controls | body | 13.90 s | 8.30 s | 7/4 |
| Avalonia.Controls | api | 15.65 s | 12.49 s | 7/4 |
| Avalonia.Controls | tool | 15.92 s | 10.29 s | 5/6 |
| Orchard CMS | body | 129.46 s | 13.62 s | 9/193 |
| Orchard CMS | api | 126.35 s | 103.73 s | 0/202 |
| Orchard CMS | resource | 47.52 s | 11.66 s | 199/3 |
| Orchard CMS | tool | 123.48 s | 84.75 s | 0/202 |

Avalonia.Controls covers seven projects / eleven configurations, not the full
repository. All compared semantic outputs match raw MSBuild for its body, API
and generator edits. This slice does not qualify an Avalonia resource edit.
Orchard covers all 202 configured CMS projects. Its Razor resource edit matches
all assemblies; two intermediate static-web-assets cache JSON files differ.
Body/API/generator comparisons have 898 differing captured paths, including
copies, consistent with the earlier nondeterministic-generator observations;
these comparisons do not establish byte-for-byte parity. File sets match in
all cases. The final graph output serves the setup page and three embedded
assets without creating a tenant.

The default generated contract conservatively invalidates implementation
consumers for package/custom-target graphs. That produced the 193-project body
rebuild above. The reviewed opt-in contract below removes that cascade without
changing the default; broad migration parity is still required.

Reproduce on disposable, declared-input workspaces using the reviewed edits:

```sh
RULES_MSBUILD_DOTNET_ROOT="$SDK" python3 tests/graph_build/upstream_edits.py \
  "$WORKSPACE" "$CONTRACT" "$CACHE" \
  tests/graph_build/upstream/orchard_edits.json "$RESULTS"
```

Use `avalonia_edits.json` for Controls. The script checks each replacement,
restores source files, records complete output differences and retains logs.
A successful script run means measurements completed; inspect differences
before claiming parity. Generated contracts and package closures are described
in [migration qualification](project-cache-migration.md#upstream-migration-qualification).

## Reviewed Orchard dependency contracts

The generated Orchard mapping now opts into reviewed reference boundaries.
Compiler consumers use reference assemblies; analyzer/task dependencies retain
implementation fingerprints. Dependency configuration, resources and other
noncompiler inputs remain in consumer keys. See the
[contract and correctness tests](project-cache-migration.md#reviewed-dependency-roles).

On the same 202-project CMS slice at revision
`04467a3438d4255627c1a478598a1585b3ff2947`, the body edit rebuilt **one project**
and reused **201**. End-to-end runner time fell from the earlier **129.46 s** to
**40.01 s** (3.24x); paired warm raw graph MSBuild took **15.87 s**. All captured
DLL/PDB/JSON/XML/resource output paths and bytes matched raw MSBuild. This fixes
the unnecessary body-edit rebuild cascade, while the runner remains 2.52x slower
than the paired warm raw build.

The other edits retain the expected invalidation:

| Edit | Generic runner | Warm raw graph MSBuild | Hits/misses | Differing paths |
| --- | ---: | ---: | ---: | ---: |
| body | 40.01 s | 15.87 s | 201/1 | 0 |
| API | 120.70 s | 84.56 s | 9/193 | 898 |
| Razor resource | 40.93 s | 13.30 s | 199/3 | 2 |
| generator | 121.21 s | 92.58 s | 0/202 | 898 |

All output file sets match. The API/generator differences include copied
assemblies and retain the earlier parity limitation. The resource differences
are the two intermediate `rjsmcshtml.dswa.cache.json` / `rjsmrazor.dswa.cache.json`
files; its assemblies match. The final CMS output served the setup page and three
embedded assets with HTTP 200, without creating a tenant. Full API/generator byte
parity and native Linux sandbox qualification remain default-switch gates.

The runner's 39.96 s internal total included 16.75 s build/snapshot handling,
9.96 s input hashing and 5.25 s evaluation. The remaining 8.01 s primarily covers offline
Restore and setup. Final input verification is inside build/snapshot handling. Only one project compiled; output replay
and validation now account for much of the remaining work.

These are single samples on macOS ARM64/SDK 10.0.400 with four MSBuild nodes.
The runner starts from deleted declared outputs and a local cache; raw MSBuild
retains incremental outputs and excludes Restore. Small qualification tests ran
concurrently during part of the run. This is not a Bazel or remote-cache timing,
and the historical before/after ratio is not an isolated benchmark median.
Timing used the dependency logic at `c43d873`, before the contract-version guard;
that guard changes accepted contract versions, not cache-key or execution logic.
Reproduce with the `upstream_edits.py` command above after syncing with
`tests/graph_build/upstream/orchard.json`.

## Orchard reference-boundary follow-up

[Testing merged PR #92 on Orchard](orchard-reference-boundaries.md) preserves the
202-project graph. Three paired incremental samples give median Bazel/raw times
of **0.719/12.752 s no-op**, **2.686/11.016 s body**, and **154.178/29.798 s API**.
Body edits compile one project; API additions still compile 193. Orchard does not
opt out of transitive references, and content-dependent asset paths change 87
module/theme reference assemblies. The follow-up uses a local disk cache and
alternates build systems; do not treat its difference from the older protocol as
an isolated regression or speedup. See the report for ranges and limits.

## Generated Orchard workflow baseline

The [generated-graph workflow report](project-sync-workflow-costs.md) compares
202 projects on one 6-CPU/10-GiB Linux ARM64 VM, SDK 10.0.400, Bazel 9.2.0,
two build slots and a 4096-MB retained-worker budget. Two-sample medians are:

| Case | Bazel | Raw MSBuild |
| --- | ---: | ---: |
| Cold build | 162.374 s | 67.127 s |
| Warm no-op | 0.584 s | 11.169 s |
| Body edit | 3.068 s | 10.960 s |
| API edit | 132.755 s | 27.537 s |

Raw forced restore costs another 3.572 s median over warm downloads. Cold Bazel
includes package extraction and runner/runtime bootstrap. Cold and API builds
remain **2.42× / 4.82× raw build time**; no-op and body edits are **19.1× / 3.57×
faster**. Keep the report's ranges and scope alongside these small-sample medians.
An unbounded worker run ran into memory pressure and is excluded. A one-worker
control was slower for both cold compilation and API edits.

Sharing parsed MSBuild documents within a sync invocation reduces unchanged
Orchard sync from **16.17 to 8.39 seconds** median (**48.1% less time**), while
preserving generated bytes. Builds of committed declarations do not run sync.

The [reference-boundary synthetic](reference-invalidation.md) proves that an
explicit direct-reference boundary cuts an eight-consumer API addition from ten
compilations to two (Bazel 9 median 1.012 s forced-transitive control versus
0.269 s inferred direct references). This does not change the Orchard figures.
API-edit improvement across a wider scenario matrix is the ongoing
[step 9](roadmap.md#9-improve-incremental-api-edits-across-a-broader-scenario-matrix).
The one shared-project API case above is a baseline, not a representative sample
of every API change.

A [later Orchard matrix](orchard-api-edit-matrix.md) observed 2, 11 and 193
compilations for leaf, intermediate and shared API additions. Raw MSBuild's
binlog also contained 193 compiler tasks for the shared edit. Stable-path and
direct-reference experiments did not produce a measured wall-time win; the
profile points to compiler, restore and staging work within necessary actions.

An opt-in [project-specific prepared Restore experiment](prepared-project-restore.md)
kept Restore cached across the shared Orchard API edit. One matched run reduced
the edit from **124.324 to 118.108 s (5.0%)**, while the initial graph grew from
139.042 to 198.271 s. Raw MSBuild took 32.448 s for that edit in the same
container. The cold cost and small incremental gain keep this mode off by default.

## Latest compiler and memory qualification

On one **8-CPU/8-GiB Linux ARM64 VM**, runtime cold compilation takes
**301.83 s**, versus **313.21/322.60 s** with per-consumer analyzer paths:
about **5% less time** than the control mean. Both use two jobs/workers and a
4096-MB native worker budget. Raw MSBuild takes **139.75 s**, with **72.69 s**
restore separately: the candidate remains **2.16× raw build time**. These are
two controls and one candidate, not a general speedup claim.

The same VM also qualifies these large graphs with four jobs, two workers and
the same memory budget. Each timing is one observation; raw was not rerun for
these two graphs in this series.

| Workload | Cold | Body edit | API edit | Independent HTTP recovery |
| --- | ---: | ---: | ---: | ---: |
| Orchard, 202 actions | 129.24 s | 1.10 s | 105.69 s | 25.05 s |
| ASP.NET Core slice, 278 actions | 124.88 s | 0.72 s | 77.58 s | 11.71 s |

Both recoveries execute no compilation and match every checked producer output
(1,576 Orchard / 4,433 ASP.NET files). Orchard's recovered Razor page and assets
pass. A separate 40-edit runtime stress run with a 1024-MB budget completes
three worker evictions; median edits take 1.52 s and sampled post-build compiler RSS peaks
at 503 MiB. This excludes other worker/JVM memory and active-build peaks.

See [conditions, controls and limits](runtime-cold-timing.md#matched-single-vm-compiler-comparison)
and [compact evidence](runtime-compiler-profile-evidence.json). The older samples
below use different resource settings and retain their original comparison scope.

## Warm builds and edits

A body edit changes executable code without changing the public reference
assembly. Bazel recompiles the producer and updates runtime outputs while reusing
consumer compilation. API changes can invalidate consumers and are a different
workload. These rows measure builds, not test execution.

| Workload / case | Bazel | Raw MSBuild | Samples and scope |
| --- | ---: | ---: | --- |
| Orchard, no-op | 1.60 s | 13.59 s | One run per case; full 202-project CMS closure |
| Orchard, core-library body edit | 1.59 s | 10.85 s | One run; one library recompiles |
| Orchard, setup-module CSS edit | 15.46 s | 11.80 s | One run; four projects rebuild |
| ASP.NET Core, no-op | 0.21 s | 11.85 s | Medians of three; 220 projects / 275 framework builds |
| ASP.NET Core, ObjectPool body edit | 0.97 s | 13.31 s | One run; one selected framework target recompiles |
| Runtime, Pipelines body edit | 2.081 s | 11.576 s | Medians of three; compiler reuse, retained server/workers |
| Runtime, Pipelines API edit | 7.970 s | 13.945 s | Medians of three; four Bazel managed actions execute |

The recorded runtime body edit is **5.56× faster** than raw MSBuild; the API edit
is **1.75× faster**. Both sides build the same managed roots, excluding native
products, host composition and test execution. Its no-op medians are 0.168 s
for Bazel and 10.965 s for raw MSBuild.

Sources: [Orchard](orchard-explicit-performance.md),
[ASP.NET Core](aspnetcore-large-graph.md), and
[current runtime comparison](runtime-cold-timing.md).

## Cold compilation

Cold here means fresh build outputs with SDKs and packages already available.
Source acquisition, BUILD declaration preparation and tool downloads are excluded.
Restore and output composition differ between workloads; read the boundaries
below before comparing ratios.

| Workload | Bazel | Raw MSBuild | Boundary |
| --- | ---: | ---: | --- |
| Orchard CMS | 128.59 s | 70.15 s | 202 projects; Bazel includes package extraction, raw includes local-feed restore |
| ASP.NET Core managed graph | 136.63 s | 44.55 s | Original paired clean-output observations; two build slots each, warm downloads |
| Runtime managed roots | 259.96 s | 139.31 s | Same 38 configured roots / 253 project paths; compiler reuse; raw restore separately took 73.83 s |

These are single observations, not repeated medians. Runtime's managed comparison
is **1.87× raw build time**, excluding raw restore. Compiler reuse reduced the
fresh Bazel baseline from 465.67 to 259.96 s (**44.2% less time**). This changes
the runtime fixture’s explicit compiler properties, not the generic rule API.
It retains substantial compiler memory: 10.23 GiB aggregate RSS observed in a
16 GiB VM. The earlier full host build takes
788.57 s with one worker and includes native products and host composition; that
is not the matched managed-only comparison.

A later ASP.NET Core cache-producer experiment reduced cold time from 141.24 to
129.91 s with uploads enabled in both runs. It is a separate one-run comparison;
the earlier raw baseline did not upload an action cache.

Sources: [Orchard protocol](orchard-explicit-performance.md),
[ASP.NET Core baseline](aspnetcore-large-graph.md),
[later ASP.NET Core profile](aspnetcore-cache-profile.md), and
[runtime cold comparison](runtime-cold-timing.md).

### Later Orchard version comparison

A separate Bazel 9.2 run series recorded medians of three: **138.20 s cold,
1.30 s no-op, 2.32 s body edit and 15.94 s CSS edit**. It did not rerun raw MSBuild,
so the paired raw comparisons above retain their original 8.4.2 measurements.
Relocated 9.2 cache recovery took 37.56 s in one trial. The comparison found no
clear compilation speedup over 8.4.2, and noted possible disk-pressure effects.
See the [fixed-revision version-comparison report](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/bazel-9.2-orchard-performance.md).

## Remote-cache recovery

These measurements use fresh Bazel output bases, no disk action cache and full
output downloads. SDK/package acquisition is warm. Caches use loopback or a
private VM network on the same host, **not a WAN**. Recovering cached test results
is different from executing tests.

| Workload | Recovery time | What was verified |
| --- | ---: | --- |
| Orchard | 37.00 s, one run | Relocated checkout, deleted producer outputs; 489 remote hits, no compilation; recovered app and assets run |
| ASP.NET Core | 11.39 s median of three | Fresh bases in a warm VM; all 578 actions recovered |
| ASP.NET Core, independent VM | 15.23 s, one run | Producer VM deleted; recovered assemblies and composed package files match |
| Avalonia themes + IDL | 9.28 s median of three | Independent consumer, producer stopped; 98 hits, no compilation/generation; 254 artifacts match |
| Runtime managed roots, compiler reuse | 10.89 s, one run | Independent consumer, producer stopped; 671 hits, no compilation; 394 reference DLLs match |
| Runtime host | 28.45 s, one run | Producer stopped; all build actions recovered; 2,806 output hashes match |

Runtime then recovered seven cached test results in 7.63 s. Forcing actual test
execution took 54.90 s and preserved case-outcome parity. Those are separate
invocations, each including startup and analysis.

Sources: [Orchard recovery](orchard-explicit-performance.md),
[ASP.NET Core cache profile](aspnetcore-cache-profile.md),
[Avalonia recovery](avalonia-http-cache.md), and
[runtime recovery](runtime-cold-timing.md).

## Environments and interpretation

- All headline workloads used Linux ARM64 Apple containers and SDK 10.0.400.
- Orchard used Bazel **8.4.2**, four VM CPUs / 8 GiB, two compiler workers versus
  four raw MSBuild nodes. These older results do not establish timing on the
  8.8 baseline; the separate 9.2 series above supplies version-specific evidence.
- ASP.NET Core used Bazel 9.2.0, four VM CPUs / 8 GiB and two local build slots.
  The later cache profile allowed 32 pending actions while retaining two CPU slots.
- Runtime used Bazel 9.2.0 and eight VM CPUs / 16 GiB. Timings cover the earlier
  seven-suite fixture, not the later eight-suite/source-only-host extension.
- Avalonia recovery used Bazel 9.2.0 and four VM CPUs. Its theme-only raw build
  omits the extra IDL action, so it is not a matched recovery comparison.
- Warm results depend on retained state; cache recovery depends on equivalent
  declared inputs and available cache entries. Neither predicts cold performance.
- Phase totals summed across workers overlap. They are not additive wall time.

For smaller Serilog, Polly and Spectre graphs, see the
[small-project benchmark](oss-build-benchmarks.md). For Avalonia compilation and
XAML edits, see the [theme graph](avalonia-xaml-subset.md). Qualification and known
test failures are documented separately in [current support](implementation-plan.md)
and [Bazel tests](bazel-test.md).

## Reproduce and investigate

Use each linked report's pinned source, harness and environment. Record actual
SDK/Bazel versions, CPU/worker limits, cache state, restore scope and output-download
mode. Use unique edits to avoid accidentally timing a cached previous edit, and
verify compilation counts, output hashes and test outcomes separately from time.

The main remaining performance work is broad API-edit invalidation; cold
compilation remains another substantial cost. The [roadmap](roadmap.md) tracks
both; [cold-start profiling](explicit-cold-profile.md),
[staging](worker-staging.md), [evaluation](project-evaluation-removal.md) and the
[ASP.NET Core cache profile](aspnetcore-cache-profile.md) explain measured costs
and previous reductions. Detailed reports are evidence; this page is the entry point.

## Current benchmark tools

Pinned [bazel-bench](https://github.com/bazelbuild/bazel-bench) measures
independent analysis, clean-output builds and warm no-ops. The shared scenario
driver measures stateful edits, raw MSBuild and HTTP-cache recovery while checking
compilation counts, artifact hashes and runtime/test outcomes. Failed commands
remain in the recorded samples and logs.

From Bash after normal tool setup, a small synthetic qualification is:

```sh
bash scripts/setup-bench.sh
source scripts/env.sh
bash scripts/dotnet.sh build tools/ExplicitBuild/ExplicitBuild.csproj -c Release
python3 benchmarks/synthetic.py /tmp/bench-inputs --projects 8
python3 benchmarks/snapshot.py /tmp/bench-inputs /tmp/bench-source
python3 benchmarks/run.py --source /tmp/bench-source --output /tmp/bench-results \
  --versions 8.8.0 9.2.0 --mode clean --runs 5
```

`run.py` requires a clean, prepared repository snapshot. Its modes are
`analysis`, `clean` and `noop`; downloads, package preparation and filesystem
caches are warm. Bazel-bench starts the server before timing, and its memory
value is the Bazel JVM heap after GC, not the process tree. Do not combine
those samples with end-to-end startup or raw-MSBuild ratios. Use
`benchmarks/compare.py RESULTS NEW_OUTPUT` for a matched shared-timer repeat.

For a stateful, freshly prepared Orchard workload:

```sh
python3 benchmarks/scenarios.py compiler orchard WORKSPACE NEW_BASE NEW_REPORT \
  --workers 2 --edits
```

`benchmarks/scenarios.py` retains workload adapters for Orchard, Avalonia,
ASP.NET Core and runtime; their fixture reports define preparation, targets,
cache flags and correctness controls. Run revisions serially with the same
CPU/worker/memory limits, SDK and cache state. The
[original tooling qualification](https://github.com/keegan-caruso/msbuild-bazel/blob/4ab387c59ddf5fda46d15646cf0f738d9a0026a0/docs/performance.md#current-benchmark-tools)
records the migration samples and detailed driver usage.

## Remote Avalonia qualification

The [11-project remote run](avalonia-remote-execution.md) separates cold builds,
warm edits and independent recovery. Three fresh-consumer samples measured
13.42 s median for full downloads and 9.57 s for top-level downloads; received
traffic fell from 927.09 MB to 2.91 MB. These include remote bootstrap and
transfer, not a matched raw-MSBuild comparison.

## Project facade analysis

A 200-project, two-framework synthetic measured 965 ms median analysis with
direct variant labels versus 1,261 ms with facades on macOS ARM64/Bazel 9.2.0.
Configured targets rose from 841 to 1,241; no compilation executed. The sample
ranges were broad, so this illustrates extra analysis work, not a stable latency
prediction. Use direct variant labels where that matters. Reproduce with
`tests/explicit_msbuild/profile_facades.py`; the
[raw samples](project-facade-evidence.json) retain the details.
