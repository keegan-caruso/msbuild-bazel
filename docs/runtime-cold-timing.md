# Runtime cold-build and recovery timing

## Current managed baseline and compiler reuse

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
