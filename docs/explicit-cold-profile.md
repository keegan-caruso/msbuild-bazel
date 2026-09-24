# Cold Linux worker profile

Profiled the explicit-rule implementation based on `2deee67`, using the same
129-project package-free binary tree, .NET 10.0.400, Bazel 8.4.2, Ubuntu 22.04
ARM64 Apple container, four vCPUs and 6 GiB RAM. All builds ran on native Linux
storage. SDK/repository downloads and runner bootstrap were prepared beforehand;
action caches were disabled. No production optimization was applied in this
experiment. The new instrumentation is opt-in with `profile_build = True`.

## End-to-end boundaries

| Run | Startup, repository setup and analysis | Build actions | Combined |
| --- | ---: | ---: | ---: |
| First control, new Bazel workspace | 4.81 s | 25.37 s | 30.18 s |
| Instrumented, restarted server | 1.90 s | 24.92 s | 26.82 s |
| Second control, restarted server | 1.94 s | 25.37 s | 27.30 s |
| Instrumented, restarted server | 1.93 s | 25.47 s | 27.40 s |

Every build starts fresh compiler workers and empty project outputs. These are
cold processes/outputs, not flushed OS page caches. Controls average **25.37 s**
and instrumented builds **25.19 s**: there is no observed instrumentation penalty
beyond run-to-run variation. Two separately cold raw-MSBuild runs with task
summaries took **7.14 / 6.56 s** (6.85 s mean). The performance gap remains.

## Where action time goes

The following are **summed wall durations across all 129 actions**, averaged
across the two instrumented runs. They overlap in real time across four workers;
they must not be added to, or interpreted as portions of, the 25-second wall clock.
They are useful for comparing repeated work and available optimization scope.

| Non-overlapping broker/child work | Summed worker-seconds | Share |
| --- | ---: | ---: |
| Original project evaluation and declaration validation | 11.37 | 13.9% |
| Restore project evaluation | 10.58 | 12.9% |
| Restore execution | 16.90 | 20.6% |
| Build project evaluation (also includes prior restore teardown) | 10.09 | 12.3% |
| Build execution | 19.80 | 24.2% |
| Snapshot verification/staging | 10.09 | 12.3% |
| Request cleanup/identity, preparation and publication | 2.20 | 2.7% |
| Remaining child/protocol/teardown overhead | 0.94 | 1.1% |
| **Total measured action work** | **81.97** | **100%** |

The three explicit evaluation phases total **32.04 worker-seconds (39%)**.
Restore evaluation plus execution totals **27.48 worker-seconds (34%)**; this
number overlaps the evaluation subtotal and is not an additional category.

MSBuild's event timings further explain the execution phases. These task/target
values are **inclusive, nested within the table above**, not additive:

| Task or target | Summed seconds |
| --- | ---: |
| `_FilterRestoreGraphProjectInputItems` target | 8.04 |
| `_GenerateRestoreGraph` target | 3.25 |
| `RestoreTask` task (NuGet restore proper) | 1.26 |
| `Csc` task (compiler-server request) | 7.93 |
| `ResolveAssemblyReference` task | 1.19 |
| `GenerateDepsFile` task | 0.35 |
| `ResolvePackageAssets` task | 0.24 |

In this SDK's `sdk/10.0.400/NuGet.targets`, `_FilterRestoreGraphProjectInputItems`
invokes an MSBuild task for `_IsProjectRestoreSupported` under restore-specific
properties. `_GenerateRestoreGraph` performs further MSBuild calls. Those calls
still occur for each isolated project, even though Bazel already supplies the
project graph and this fixture has no package dependencies. The aggregate MSBuild
wrapper-task time in the worker is 12.29 s. The actual NuGet `RestoreTask` is only
1.26 s, so the dominant restore work here is SDK metadata/graph preparation.

Raw MSBuild's summed `Csc` task time is **6.28 s**, compared with **7.93 s** in the
workers. Compiler work is therefore a small part of the overall gap. Wrapper tasks
such as `MSBuild` and `CallTarget` recursively include dependency waits; their raw
aggregate totals must not be compared as exclusive CPU time.

## Startup and scheduling

The first project in each compiler process averages **1.35 s** of measured child
phases, versus **0.51 s** for subsequent projects. The difference is about 0.84 s
per worker, or 3.38 summed worker-seconds for four workers. This is an observational
first-request warmup comparison, not a separately isolated startup experiment.
Repeated per-project work is much larger than this warmup difference.

Bazel's trace reports 83.16 summed seconds waiting for workers and 2.74 summed
seconds setting up their inputs. Copying outputs back through the worker protocol
is negligible. The average dependency critical-path component total is 7.30 s,
well below the 25-second elapsed build: four-worker throughput/resource contention
also matters. Critical-path and trace categories overlap; none are additive to the
phase table. Increasing concurrency was not tested and would confound this
four-vCPU comparison.

## Next changes, in priority order

1. **Remove repeated restore graph preparation from compilation.** Make resolved
   SDK/NuGet metadata a Bazel input/action with explicit package/framework/config
   identity. Preserve package selection, generated imports and SDK behavior. This
   targets the 27.48 worker-seconds spent evaluating/running Restore, including
   the repeated project-support checks. The package-free slice is a useful first
   control, not justification to bypass restore for arbitrary projects.
2. **Fold declaration validation into an evaluation already required for building.**
   The dedicated original-project evaluation costs 11.37 worker-seconds. Retain
   dependency/item validation without reconstructing the project separately.
   Post-restore imports still require correct reevaluation until step 1 supplies
   those inputs up front.
3. **Profile and reduce SDK input rescanning within snapshot staging.** This phase
   costs 10.09 worker-seconds. The broker currently resolves paths for every SDK
   input on every request before skipping pinned SDK files. Any once-per-worker
   shortcut must preserve tool identity and input-verification guarantees.

These are measured work categories, not promised wall-clock savings. Full Orchard,
Razor, package-heavy projects, large source files, network caches, and different
hardware remain separate qualifications.

## Reproduction and evidence

Build `tools/ExplicitBuild`, set `RULES_MSBUILD_DOTNET_ROOT`,
`RULES_MSBUILD_BAZEL`, and `RULES_MSBUILD_REPOSITORY_CACHE`, then run inside the
pinned native Linux container:

```sh
python3 tests/explicit_msbuild/cold_profile.py /tmp/cold-profile /evidence
python3 tests/explicit_msbuild/summarize_cold_profile.py /evidence
```

The harness alternates uninstrumented/instrumented builds, checks that all 129
worker records exist and that profiling yields 129 compiler records. It retains
per-project phases, CPU counters, task/target counts, logs and Bazel traces.
Child CPU counters exclude Roslyn's separate compiler-server process. The task
logger uses MSBuild event timestamps; phase/broker measurements use Stopwatch.

Checked-in [summary](evidence/explicit-cold-profile/summary.json) and
[wall-time samples](evidence/explicit-cold-profile/results.json) preserve the
measurements. Detailed local evidence is under `artifacts/cold-profile/`.

Validation passed: the repository's .NET and Starlark checks, all four cold
129-project builds, profile-record invariants, and execution of the built app
(expected result: `64`). The temporary profiling container was removed after
preserving its evidence.
