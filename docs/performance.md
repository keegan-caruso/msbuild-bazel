# Performance

Warm incremental builds and remote-cache recovery are the strongest measured
cases. **Cold compilation remains slower than raw MSBuild.** There is no single
speedup that describes all three scenarios.

These are recorded results from pinned qualification workloads, not a benchmark
of every commit on main. Detailed reports below retain commands, samples and
machine-readable evidence. No new measurements were taken for this summary.

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
| Runtime, Pipelines body edit | 3.495 s | 11.274 s | Medians of three; retained Bazel server/worker versus shared raw compiler |

Runtime's verified Bazel 9.2 repeat is **3.23× faster** than its separately
captured raw baseline. Raw covers managed outputs; Bazel also checks native
products and updates the host layout. Batch Bazel takes 9.691 s for the same edit,
so keeping the server and worker alive matters.

Sources: [Orchard](orchard-explicit-performance.md),
[ASP.NET Core](aspnetcore-large-graph.md),
[runtime version-verified repeat](runtime-cache-diagnosis.md) and
[raw runtime comparison](runtime-leaf-timing.md).

## Cold compilation

Cold here means fresh build outputs with SDKs and packages already available.
Source acquisition, BUILD declaration preparation and tool downloads are excluded.
Restore and output composition differ between workloads; read the boundaries
below before comparing ratios.

| Workload | Bazel | Raw MSBuild | Boundary |
| --- | ---: | ---: | --- |
| Orchard CMS | 128.59 s | 70.15 s | 202 projects; Bazel includes package extraction, raw includes local-feed restore |
| ASP.NET Core managed graph | 136.63 s | 44.55 s | Original paired clean-output observations; two build slots each, warm downloads |
| Runtime managed roots | 492.09 s | 139.59 s | Same 38 configured roots / 253 project paths; two workers or nodes; raw restore separately took 72.04 s |

These are single observations, not repeated medians. Runtime's managed comparison
is **3.53× raw build time**, excluding raw restore. Its full host build takes
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

The main remaining performance work is cold compilation. The
[roadmap](roadmap.md) tracks it; [cold-start profiling](explicit-cold-profile.md),
[staging](worker-staging.md), [evaluation](project-evaluation-removal.md) and the
[ASP.NET Core cache profile](aspnetcore-cache-profile.md) explain measured costs
and previous reductions. Detailed reports are evidence; this page is the entry point.
