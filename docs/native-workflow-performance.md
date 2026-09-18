# Complete native Build/Test measurements

This records the integration baseline. The subsequent [overhead follow-up](native-workflow-optimization.md) records implemented optimizations and new measurements.

## Protocol

`tools/measure_native_workflow.py` compares ordinary MSBuild Build plus direct
VSTest with the integrated native workflow on pinned Serilog
`49b5339ce85385dc52d4d8e8f2b8308becf23506`, SDK 10.0.400, native macOS ARM64/Nix.
The probe writes its protocol before running samples. Three repetitions cover:

- Cold: fresh build, preparation and Bazel state, with acquired tools/packages.
- Seeded: first project-cache consumption after the cold build.
- Unchanged: retained preparation and an outer Bazel build-action hit.
- Library implementation edit and test implementation edit.
- Recovery: a fresh source, preparation and Bazel state, with only sealed project
  bundles transferred and the producer source/state removed.

Every sample executes exactly one real approval test; Bazel test-result caching
is disabled for comparison. Raw/native runtime bytes must match except for the
previously documented raw-only coverage-path diagnostic. Compiler counts and
actual test action counts are checked, not inferred from elapsed time.

The default `reuse` profile invokes the one-shot CLI and includes Python startup.
The optional `trusted-incremental` profile retains a Python controller with the
explicit protected-Nix-store and guarded C# content-refresh policies. It does not
represent the default CLI or a generally available persistent service. Both keep
Bazel running within a sequence. Raw/native order and profile order alternate
between repetitions.

Wall time includes native SDK identity checks, preparation, input/seed staging,
Bazel startup when needed, build/test execution, final lease validation and local
project-cache publication. Initial SDK/tool/source/package acquisition and NuGet
Restore are excluded from both paths: the workflow consumes already-restored
inputs. Raw runtime hashing after execution is diagnostic and outside its timer;
the native timer includes report/runtime hashing. OS filesystem caches are not
flushed. The three fresh-preparation controls use the same final source and warm
build cache while explicitly turning preparation reuse off.

The predeclared steady-state target is `raw median × 1.25 + 0.250 seconds` for
unchanged, library-edit and test-edit cases. Correctness acceptance and meeting
that performance target are reported separately. Cold and recovery timings are
reported without treating startup cost as free.

## Corrections found while measuring

The ordinary library implementation edit compiled both projects in this pinned
SDK/project configuration; the probe checks that observed work set rather than
assuming reference-only incrementality.

Fresh preparation initially enabled workload discovery while leased discovery
disabled it. This produced different SDK-import identities despite equal runtime
bytes and caused avoidable mode-switch cache misses. The integrated fresh path,
its fallback, evaluated native execution and raw comparison now explicitly disable
the workload resolver for this non-workload net10.0 slice. Workload support is not
added. Runner/controller digests invalidate old cache identities automatically.
The earlier interrupted measurement attempts are not used as qualification data.

## Reproduce

Inside the pinned Nix shell, with the checkout and packages already acquired:

```sh
python3 tools/measure_native_workflow.py --source /path/to/serilog \
  --packages /path/to/packages --output /private/tmp/native-measurements
```

Use a new, short output path. The report retains individual samples, phase timings,
compiler/test counts, runtime hashes, medians, ranges and the explicit target
result. Per-sample native reports include Bazel logs, execution provenance and
TRX; raw samples retain build/VSTest logs and TRX.

## Measured results

All 36 paired samples and three fresh-preparation controls passed: 75 actual
Build/Test executions, each with one passing approval Fact and no skips. All
runtime comparisons and expected compile counts passed. Both profiles missed the
predeclared performance target. Medians below are seconds across three samples.

| Case | Raw paired with CLI | Native CLI + reuse | Raw paired with retained | Retained, trusted + incremental |
| --- | ---: | ---: | ---: | ---: |
| cold | 1.370 | 12.952 | 1.279 | 11.620 |
| seeded | 1.054 | 5.270 | 1.033 | 3.820 |
| unchanged | 1.061 | 4.187 | 1.061 | 2.721 |
| body | 1.252 | 10.794 | 1.213 | 5.125 |
| test-edit | 1.070 | 10.533 | 1.068 | 4.792 |
| recovery | 1.286 | 12.727 | 1.327 | 10.789 |

Unchanged native phase medians:

| Phase | Default CLI | Optional retained controller |
| --- | ---: | ---: |
| identity | 0.467 | 0.016 |
| prepare | 1.502 | 1.022 |
| stage | 0.296 | 0.305 |
| bazel | 1.095 | 1.113 |
| publish | 0.028 | 0.028 |
| leaseExit | 0.621 | 0.169 |

Phase medians need not sum to the median total. CLI startup and minor reporting/
cleanup costs also sit outside these subphase timers but inside the CLI total.

The fresh-preparation control median was **4.855 s**.
Default unchanged reuse was about **13.8% faster** than that control;
the optional retained profile was about **35.0% faster** than default reuse.
These are combined-profile observations, not isolated attribution to each option.
The default source-edit path conservatively rediscovers and republishes a plan;
the optional guarded source refresh avoids rediscovery but still materializes and
verifies the updated payload.

## Conclusion and next performance work

Build/Test integration and preparation reuse are correct for this slice, but
**raw-MSBuild parity is not achieved**. The default unchanged path is about 3.95×
raw; the optional retained path is about 2.56×. Recovery compiles zero projects,
but fresh preparation and Bazel startup dominate total time on this small graph.

The next performance experiments should target immutable prepared-input reuse
and reduced copying, reuse of verified package payloads during eligible source
refresh, and avoiding duplicate identity scans while preserving the final lease
checks. Any such change must retain package/source mutation, namespace,
corruption and publication controls. These are proposed follow-ups, not measured
improvements or reasons to weaken the target. Larger projects and remote-cache
network costs remain separate measurements.

## Final validation

The final tree passes 72 preparation-reuse tests, 23 native-cache tests, the owned
.NET build/style checks and pinned Starlark formatting/lint. Generated workflow
Starlark also passes the pinned formatter. A final real cold/reused Build/Test
smoke run compiled two/zero projects respectively, reused preparation on the
second run, and matched the benchmark raw runtime bytes. These checks include
the final formatting and shared-policy regression fixes made after measurement.
No GitHub CI was run; this evidence is local macOS ARM64.
