# Runtime cold-build and recovery timing

Runtime v10.0.0 (`60629d14374c56f1cb51819049ad1fa529307f8d`), SDK 10.0.400,
Bazel 9.2.0, Linux ARM64; 8 CPUs and 16 GiB per container. The fixture contains
273 configured upstream nodes, seven suites, 121 source-built framework
assemblies and eight native runtime products.

## Independent HTTP recovery

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

## Cold results

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
