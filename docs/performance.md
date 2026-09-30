# Performance

No-op builds, method-body edits and remote-cache recovery are the strongest
measured cases. **Cold builds and larger-graph API edits remain the main gaps.**
Body and API edits are the primary scorecard; there is no single overall speedup.

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
278.66 s bootstrap/setup observation is retained, but matched cold attribution
remains open. See [ranges, commands and limits](graph-cache-plan.md#collections-incremental-scorecard).

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
