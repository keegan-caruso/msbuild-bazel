# Runtime cold-build and recovery timing

## Earlier managed baseline and compiler reuse

**Measurement caveat:** a later host audit found 16 GiB physical RAM. The earlier
16 GiB build VM and other running VMs could overcommit it. The historical samples
below remain recorded observations, not a healthy build-server performance
guarantee. The follow-up compiler experiments explicitly separate overcommitted
diagnostics from measurements with one memory-budgeted build VM.

The post-cleanup main revision `0c1522814ce5a8a074ddcb5198a0ce4fc9a1ffa3`
was measured again against the same pinned runtime source and 38 managed roots.
Both sides use two build slots; all 253 project paths / 273 configurations remain
in scope. These builds exclude native products, host composition and test execution.

The baseline took **465.670 s**, versus **139.311 s** for raw MSBuild (3.34×).
Raw restore took another **73.829 s**, reported separately. Raw compiled 364
project invocations and its following no-op compiled none. Unique edits gave
these medians of three:

| Case | Bazel baseline | Raw MSBuild |
| --- | ---: | ---: |
| No-op | 0.166 s | 10.965 s |
| Pipelines body edit | 3.148 s | 11.576 s |
| Pipelines API edit | 11.065 s | 13.945 s |

API edits change both the source and authored reference declaration. Body edits
preserve the public reference hash; API edits change it and execute four managed
actions instead of one. Every edit is unique and restored after measurement.

An independent container recovered the baseline in **15.962 s**: 671 HTTP hits,
zero managed/package execution, and all 394 declared reference DLL hashes equal
to the producer. The producer was stopped, checkout and rule paths relocated,
and the consumer used a new output base, no disk cache and full output downloads.

### Removing repeated compiler startup

The baseline's 274 action profiles spend 820.21 summed worker-seconds in the
MSBuild child, about 94% of the recorded phases. Three detailed action profiles
show compiler work dominating their evaluation and restore. Summed concurrent
phases are not wall-clock segments.

The runtime fixture had disabled shared compilation because each action gives
its package compiler a different input path. Roslyn normally derives the server
pipe from that compiler location. Its existing `SharedCompilationId` property
lets the authored fixture name the server by **locked compiler archive bytes,
package/version and SDK version**, independent of consumer source paths.
See [Roslyn's compiler task](https://github.com/dotnet/roslyn/blob/main/src/Compilers/Core/MSBuildTask/ManagedCompiler.cs).

`prepare.py` now emits those explicit properties for the runtime fixture. Each
Linux worker retains its private namespace, inputs and compiler temporary directory;
Bazel still owns action caching. The generic rules/runner and SDK behavior are
unchanged. This is qualification of the pinned runtime compiler, not a blanket
policy for arbitrary package compilers or process-global analyzer state.

An initial 266-project trial took 264.912 s. Its seven test declarations had not
yet received the new properties, so the final run below covers all 273 declarations.

The final fresh-base run took **259.958 s**, a **44.2% reduction** and **1.79×
speedup** over the current baseline. All 274 managed actions executed with no
cache hits. This is still **1.87× raw MSBuild's build time**, excluding restore.
Each cold result is one observation; the initial trial is supporting evidence,
not a repeated sample of the exact final configuration.

The final profile records 401.90 summed child-seconds, down from 820.21. Identity,
snapshot and preparation together rose from 50.79 to 61.45 seconds; the benefit
comes from compiler reuse, not reduced staging. The process sample peaked at
11 compiler processes and **10.23 GiB aggregate compiler RSS** in the 16 GiB VM.
RSS can count shared pages more than once. This does not qualify smaller machines
or place a lifetime bound on Roslyn's retained metadata/analyzer memory.

Changing declared compiler properties changes the action identity. Some DLLs
embed that identity in their PDB path, so exact before/after binary hashes differ.
`ManagedOutputComparison.cs.txt` compares assembly sets, metadata except module
IDs, complete method bodies and managed resources. It deliberately excludes PE
debug records and PDBs; this is a diagnostic equivalence check, not bitwise parity.
Independent cache recovery still requires exact hashes within one configuration.

The final edit medians are **0.168 s no-op, 2.081 s body and 7.970 s API**.
Body edits still execute one managed action; API edits execute four. Public
reference hashes and implementation restoration checks pass. An intentional
compiler error fails with CS1029, then a unique valid edit compiles successfully
in the retained worker and restoring the source restores the original bytes.
The final 609-DLL diagnostic comparison also passes all three content checks.

The optimized configuration also passes independent HTTP recovery: **10.887 s**,
671 remote hits, zero compilation and **394/394 exact reference hashes** matching
both its cold build and fresh cache seed. The producer is stopped and checkout/rule
paths are relocated. Do not attribute the difference from 15.962 s to compiler
reuse: filesystem/cache-server warmth was not controlled between recovery trials.

See [compact measurements and validation](runtime-compiler-reuse-evidence.json).

### Compiler attribution and retained memory

A detailed replay/profile of the same managed roots records **365 Csc tasks** on
Bazel versus **364** on raw MSBuild; ILLink executes **99 times** on each side.
The problem is largely the cost of those tasks, rather than a multiplied count
of project compilations. Summed Csc time is **251.67 s versus 62.45 s**; ILLink is
**100.43 s versus 78.40 s**. Bazel's build had evaluation profiling and
`ReportAnalyzer` enabled while the raw figures come from its accepted cold
binlog. These are diagnostic, cumulative task times, not an isolated speedup
comparison or additive wall-clock segments. Nested task totals overlap.
These profiles were collected before correcting host VM overcommit; use them to
locate work, not to forecast compiler latency on an adequately sized server.

`runtime/TaskProfile.cs.txt` replays a raw binlog with task/project/framework
attribution and compiler commands. The runner's opt-in `profile_build` report
also captures compiler task messages, including low-importance analyzer timing
text when the project explicitly sets `ReportAnalyzer=true`. Normal builds keep
profiling disabled.

Bazel's **total idle-worker limit alone is insufficient for a sequence of short
single-action builds**: the repeatedly used worker can be busy at every poll.
Bazel 9.2's `--experimental_shrink_worker_pool` marks it for eviction when its
request finishes. This uses Bazel's worker lifecycle; the runner needs no separate
recycling protocol. See the [pinned implementation](https://github.com/bazelbuild/bazel/blob/9.2.0/src/main/java/com/google/devtools/build/lib/worker/WorkerLifecycleManager.java).

Project-built analyzer groups now use a path derived from their complete,
verified runtime closure. Consumer-only changes no longer force a new analyzer
load location. Helper changes still invalidate the whole group; package/SDK
analyzer locations are unchanged. The broker removes preceding request inputs,
and all current analyzer inputs remain read-only. See
[the load-group contract and controls](project-built-analyzers.md).

The memory stress experiment uses 40 unique Pipelines body edits per mode. It
checks unchanged reference hashes, changed implementations and exact restoration.
The 1024 MB budget deliberately triggers eviction; it is **not a recommended default**.

```text
--experimental_total_worker_memory_limit_mb=1024
--experimental_shrink_worker_pool
--experimental_worker_metrics_poll_interval=1s
```

With deferred eviction, observed post-build compiler RSS stayed below **552 MiB**
after the first eviction; four evictions completed safely. Replacement builds
cost **4.12–6.29 s** and the median edit was **1.61 s**. Without the limit, the
40-edit run retained as much as **8.07 GiB** of aggregate compiler RSS after the
full graph. The runs start from different retained state and are not a matched
speedup comparison. RSS/PSS samples cover compiler descendants of the selected
Bazel server, not all workers/JVM memory or an active-build peak. The native
budget counts worker process trees and is a soft limit, not a hard RSS cap.
These initial stress runs also predate correction of host VM overcommit. Their
eviction and output checks establish behavior; their edit times are exploratory.

`runtime/memory_soak.py` reproduces this experiment; use `--memory-limit-mb` and
`--shrink-pool` for the bounded variant. It restores source even on failure and
stops issuing edits when the VM's available memory drops below its configured
floor. A two-second idle observation interval is outside build timing. The
active-worker kill option (`--experimental_worker_memory_limit_mb`) is not used:
it can interrupt compilation. The result qualifies these controls on Bazel 9.2;
it does not establish a universal budget or a lifetime bound without eviction.

### Matched single-VM compiler comparison

With the host overcommit corrected, the path-policy control took **313.209 s**
and **322.604 s**, bracketing the candidate at **301.828 s**. Each fresh output
base executed exactly 274 managed actions without cache hits. Both policies use
the same compiler-sharing properties, scratch leases, disabled MSBuild profiling,
two jobs/workers and a 4096-MB native worker budget with deferred eviction.
The control changes only project analyzer paths back to per-consumer locations.

The candidate is **3.6–6.4% faster**, or **5.1% below the mean of the controls**.
This is a modest configuration-specific result: two controls and one candidate,
not a broad benchmark or evidence that the cold-build gap is closed. Summed
MSBuild-child time falls from 298.62/307.44 s to 288.80 s. Snapshot/preparation
costs do not improve. All 609 DLLs pass the diagnostic metadata/method/resource
comparison described above; it excludes module IDs and PE debug/PDB data.

Raw MSBuild on the same VM takes **139.748 s** to build the same roots, after
**72.688 s** of separately measured restore; its no-op is **10.975 s**. The
candidate is **2.16× raw build time**. This bounded-worker result is not directly
comparable to the earlier 16-GiB/unlimited-worker sample at 259.958 s.

The initial overcommitted trials (322.05/333.12 s control, 295.78 s candidate)
are excluded from this comparison. Their apparent 8–11% gain is not a headline
result. The same applies to interrupted, disk-full and fixture-setup failures.

The final 8-GiB run completes **40 unique edits** with the 1024-MB stress budget.
Median edit time is **1.521 s**; post-build compiler RSS peaks at **503.5 MiB**
(PSS **468.8 MiB**). Deferred eviction completes after edits 10, 20 and 31;
replacement edits take **3.88–4.17 s**. Public references remain unchanged and
restoring source restores the exact implementation bytes. These are sampled
compiler totals, not an active-build peak or the entire process-tree budget.
Scratch-lease controls additionally cover SIGKILL reclamation, preservation of
live workers, normal cleanup and rejection of unsafe parent directories.

### Large-graph edit qualification

The follow-up uses one 8-CPU/8-GiB Ubuntu 22.04 ARM64 build VM on a 16-GiB Apple
M4 host, plus the 1-GiB HTTP cache VM. Other build VMs are stopped. SDK 10.0.400,
Bazel 9.2.0, four jobs, two worker instances and a 4096-MB native worker budget
with deferred eviction are fixed. Host swap usage declined during these runs.
SDKs, packages and declarations are prepared before timing; cold builds use new
output bases and no local/remote action-cache hits. These are single observations.

| Workload | Managed actions | Cold | No-op | Body edit | API edit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Orchard CMS | 202 | 129.240 s | 0.829 s | 1.097 s | 105.688 s |
| ASP.NET Core slice | 278 | 124.884 s | 0.829 s | 0.721 s | 77.578 s |

Both body edits execute one action and preserve all public reference hashes.
The API edits execute 193 Orchard actions and 130 ASP.NET actions. ASP.NET's
test updates its authored public-API baseline alongside the C# change; all
reference hashes restore exactly. Orchard's edited leaf restores exactly, but
65 downstream references differ after recompilation, consistent with its previously
documented [generator randomness and embedded input paths](orchard-stable-worker-paths.md).
This is separate from exact producer/consumer cache-output parity.

Orchard's setup Razor page and three embedded assets pass after restoration.
A separate cache seed with four configured workers also compiles all 202 actions
and passes those runtime checks. It takes 129.631 s including uploads; ASP.NET's
two-worker seed takes 147.327 s. These do not establish a speedup over historical
runs with different hardware/resource settings. Filesystem trimming is outside
headline timing; Orchard's restore control included maintenance and is not a
performance sample.

With that producer stopped, a new VM at relocated checkout/rule paths recovers
Orchard in **25.050 s** (489 remote hits) and ASP.NET in **11.707 s** (578 hits).
There is no compilation or package extraction. All **1,576 Orchard** and
**4,433 ASP.NET** declared reference/runtime file hashes match their respective
producers. Recovered Orchard renders the setup page and serves the same three
assets. Both consumers have fresh output bases, no disk cache, full downloads
and local-result uploads disabled. This is a local VM-network cache, not a WAN.

Final Linux acceptance and expanded analyzer controls pass on Bazel **8.8/9.2**,
including consumer-only path stability, helper invalidation, cached tool reuse
and retained-worker input isolation. Owned .NET build/style/tests and the
toolchain/Starlark checks pass; no CI was dispatched. See
[compact compiler, memory and graph evidence](runtime-compiler-profile-evidence.json).

`tests/explicit_msbuild/compiler_reuse.py` runs these controls on prepared
fixtures. Use `--edits --memory-limit-mb 4096` for compilation/invalidation,
`--cache URL` with a fresh base to seed, and `--recovery --cache URL
--expect-hashes PRODUCER_HASHES` in a relocated independent VM. `--trim` optionally
returns freed Linux filesystem blocks to the VM host outside measured calls.

### Reproduce the managed comparison

Prepare the pinned fixture through the [runtime workflow](runtime-workflow.md),
using the 38 roots recorded in the evidence JSON and a newly built runner. Export
`RULES_MSBUILD_BAZEL` and `RULES_MSBUILD_DOTNET_ROOT` to the pinned Linux tools.
The baseline uses the pre-change `prepare.py`; the optimized fixture uses the
compiler properties from this change. Keep the production runner bytes identical.

```sh
python3 tests/explicit_msbuild/runtime/managed_timing.py \
  WORKSPACE SELECTION_JSON FRESH_BASE COLD_REPORT --case cold
python3 tests/explicit_msbuild/runtime/managed_edit_timing.py \
  WORKSPACE SELECTION_JSON BASE EDIT_REPORT
python3 tests/explicit_msbuild/runtime/managed_timing.py \
  WORKSPACE SELECTION_JSON FRESH_SEED_BASE SEED_REPORT --case seed --cache CACHE_URL
```

Copy declared inputs and identical built rule tools to the second container,
relocate the checkout/rules paths, and stop the producer. Run `managed_timing.py`
with `--case recovery --cache CACHE_URL --expect-reference-hashes SEED_HASHES_JSON`
against another fresh base. Do not copy any producer output base or action cache.
The hash manifest includes DLL outputs, not Bazel's adjacent local `.params` inputs.

Use `raw_cold_timing.py FRESH_RUNTIME_SOURCE SELECTION_JSON REPORT` for the raw
cold/restore comparison, then `raw_leaf_timing.py SOURCE INVENTORY_JSON REPORT
--shared-compilation true --edit body` and a separate report with `--edit api`.
Run each timed case without competing benchmark work. Keep heavyweight MSBuild
profiling separate from headline timings. To diagnose cross-configuration DLL
differences, compile `ManagedOutputComparison.cs.txt` as a net10.0 console app
and pass the two `bazel-bin/upstream` directories. It returns nonzero on a
content mismatch within its documented comparison boundary.

## Earlier full-host qualification

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Bazel 9.2.0, Linux ARM64; 8 CPUs and 16 GiB per container. The fixture contains
273 configured upstream nodes, seven suites, 121 source-built framework
assemblies and eight native runtime products.

### Independent HTTP recovery

The producer was stopped. The consumer had a new output base, no disk cache,
and local-result uploads disabled. Its checkout and SDK were available locally;
this is a private VM-network measurement, not a WAN or tool-download benchmark.

| Phase | Wall time | Verification |
| --- | ---: | --- |
| Build and materialize outputs | 28.451 s | 280/280 managed, 149/149 package extraction, 5/5 native and 121/121 layout actions hit HTTP cache |
| Recover cached test results | 7.628 s | Seven remote test-result hits |
| Force test execution | 54.899 s | Seven suites execute and pass |

All 2,806 output hashes match the producer. Forced execution preserves raw/Bazel
case-outcome parity: 118,375 passes and 64 skips. Loaded-runtime provenance reports
zero installed runtime components. Each row is one batch-mode Bazel invocation;
startup and analysis are included. These are single observations, not medians.

### Earlier cold results

| Scope | Wall time | Actual work |
| --- | ---: | --- |
| Full Bazel host, one worker | 788.570 s | 280 managed, five native and 121 layout actions; zero cache hits |
| Bazel managed roots, two workers | 492.092 s | 274 managed actions across 273 configurations; no native builds or host composition |
| Raw MSBuild managed roots, two nodes | 139.588 s | 364 compiler calls |
| Raw following no-op | 11.021 s | Zero compiler calls |

Raw restore took **72.037 s**, separately. The managed cold ratio is **3.53×**
in raw MSBuild's favor. Both builds compile the same **253 project paths** from
the same 38 project/framework roots. Their scheduling and contract checks differ;
compiler-call counts are not equivalent to Bazel action counts, and several
projects have multiple configurations. Some raw binlog events
omit framework metadata, so only project-path equality is asserted from those
events. The full cold build reproduces all **2,806 seed hashes** exactly.

See [commands, counts and tool identities](runtime-cold-timing-evidence.json).
The full logs, binlogs and profiles are retained in the two archives recorded
there. This establishes a substantial remaining cold-compilation cost; it does
not change the independently measured warm-edit or cache-recovery results.

## Cold comparison contract

Cold means a fresh output base with both action caches disabled, or a raw source
checkout with no artifacts tree. SDK and package acquisition is warm. The full
Bazel build includes native compilation and host-layout composition. A separate
`--managed-only` build requests assembly reference output groups for the same 38
configured roots as raw MSBuild, excluding native products and host layouts.

Raw MSBuild restores the 38 configured roots first, without compiling them, then
builds those roots in one traversal with two MSBuild nodes and shared compilation.
Restore is reported separately. The raw compiler reader is built after timing;
its binlog check requires actual compilation in the cold build and none in the
following no-op. Source identity and tracked-file cleanliness are checked.

The full Bazel build uses two jobs and one compiler worker; the managed-only
comparison permits two workers to match raw MSBuild's two nodes. Both write diagnostic
logs during the timed invocation. Preparation of explicit BUILD declarations,
source acquisition and installation of pinned toolchains are excluded.

## Reproduce

Use `env` inside Apple Container's exec command; `exec -e` did not replace the
image's existing Bazel variable in this environment. The harness verifies actual
SDK/Bazel versions before timing and records the Bazel binary hash.

```sh
container exec CONSUMER env RULES_MSBUILD_BAZEL=/tmp/bazel-9.2.0 \
  python3 /work/rules/tests/explicit_msbuild/runtime/scenario_timing.py \
  WORKSPACE FRESH_BASE REPORT --scenario recovery --cache CACHE_URL \
  --expect PRODUCER_SEED_JSON --tests
```

For cold builds use `--scenario cold`, without cache/seed arguments. Add
`--managed-only --selection SELECTION_JSON --workers 2` for the managed comparison. All output bases and reports must be
new. After restore-free source checkout preparation, run:

```sh
python3 tests/explicit_msbuild/runtime/raw_cold_timing.py \
  FRESH_RUNTIME_SOURCE SELECTION_JSON REPORT
```

Record test parity separately with `subset_verify.py` and require an empty
installed-load inventory with `loaded_inventory.py --require-empty`. Timing
alone does not establish runtime provenance or cache correctness.

Exploratory managed runs were stopped while correcting contract-layout validation
and root selection. A forced-framework raw restore failed before compilation.
None of those attempts is included in the accepted timing samples.
