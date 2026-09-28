# Orchard API-edit matrix and cost attribution

This is a first slice of [roadmap step 9](roadmap.md#9-improve-incremental-api-edits-across-a-broader-scenario-matrix), not completion of its under-2× target. It uses the pinned 202-project generated Orchard CMS graph, SDK 10.0.400, Bazel 9.2.0, Ubuntu 22.04 ARM64 in an Apple container with 6 CPUs and 10 GiB RAM. Bazel ran two isolated compiler workers, `--jobs=2`, a 4096-MB retained-worker budget and a local disk cache. Downloads, graph generation and repository setup were outside edit timing. The graph used `profileBuild=true` during this exploratory series; the fixture now leaves that opt-in unset for normal builds.

The driver appended an unused public class to a leaf, an intermediate project and `OrchardCore.Abstractions`, restoring the original bytes after each build. It counted executed `MSBuildAssembly` actions from Bazel's execution log and hashed every produced reference DLL. These are **one sample per edit**, not medians or a before/after optimization result.

| API edit | Executed compilations | Changed reference DLLs | Bazel elapsed |
| --- | ---: | ---: | ---: |
| Logging.NLog leaf | 2 | 1 | 3.981 s |
| Infrastructure intermediate | 11 | 6 | 22.419 s |
| Abstractions shared library | 193 | 89 | 131.958 s |

The initial build ran 202 compilations in 151.960 s. Reverting each edit ran **zero** compiler actions (0.837, 1.129 and 8.103 s) and restored all baseline reference hashes. The broad case is consistent with the earlier [three-sample paired result](orchard-reference-boundaries.md), whose median was 154.178 s Bazel versus 29.798 s raw MSBuild under a different protocol. Do not combine their elapsed times into one speedup estimate.

## What the broad edit actually costs

A separate raw `dotnet build src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj -c Release -m:2 --no-restore -p:NuGetAudit=false -bl:api.binlog` API edit completed in 27.237 s. Replaying that binlog with `Microsoft.Build.Logging.BinaryLogReplayEventSource` and summing `TaskStarted`/`TaskFinished` timestamps found **193 `Csc` tasks**, the same count as Bazel's broad edit, with 26.100 cumulative task-seconds. The raw clean baseline contained 202 `Csc` tasks and 80.201 cumulative task-seconds. Thus the broad Bazel action count is not surplus compilation relative to raw MSBuild. Raw MSBuild does the same number of compiler tasks more cheaply after its initial build.

An instrumented repeat of the broad Bazel edit took 146.995 s and 193 compilation actions. Across those actions, the profiles recorded 76.48 cumulative `Csc` task-seconds, 9.50 s of Restore evaluation, 13.74 s running Restore targets, 7.83 s of Build evaluation, 39.44 s of worker staging and 135.63 s in the MSBuild child. Bazel's cumulative action time was 254.24 s. These are overlapping or parallel sums, **not parts of the elapsed wall time**. The task profile is diagnostic; its overhead and the different run order prevent a causal comparison with the raw binlog.

Two disposal-only experiments constrained the likely fix:

- Relaxing the SDK-only stable-path prototype inside the container reduced changed reference DLLs from 89 to 4, but still executed 193 compilations. Its single broad edit took 180.814 s. Package, analyzer and task safety checks remain unqualified, so that gate was **not** widened in production.
- Iteratively applying `transitiveCompileReferences=false` kept the full CMS build passing for 52 of 201 libraries; the other libraries needed transitive types. The broad edit then executed 173 compilations but took 131.458 s in one run, essentially the same as the original 131.958 s observation. These temporary mapping changes were **not** retained. Missing references were restored in response to compiler errors, not hidden.

Four workers were also tried. The run failed after 133 completed worker actions when Razor emitted malformed C# for unchanged, valid `.cshtml` source; it is excluded from timing claims. A subsequent unprofiled control was interrupted when the disposable container disk developed I/O errors and mounted read-only. Its result is excluded. Completed reports were preserved before deleting the disposable container. No GitHub CI was dispatched.

## Reproduce and next boundary

Prepare the generated Orchard workspace as in [generated-graph qualification](project-sync-broader-graphs.md), build it once, then run:

```sh
python3 tests/project_sync/upstream/api_edit_matrix.py \
  GENERATED_ORCHARD OUTPUT --repetitions 3
```

The driver writes action logs and hashes to `OUTPUT`, restores source bytes even on failure and shuts down Bazel. Use a fresh output directory and sample offset for additional runs; keep the CPU, memory and worker limits fixed when comparing variants. Set `projectDefaults.profileBuild=true` in a disposable mapping and resynchronize only for diagnostic profiles. The Orchard generator now leaves profiling disabled by default, matching the intended normal-build measurement mode.

The next implementation experiment should preserve **per-project incremental compiler state** without making correctness depend on a warm worker. It needs same-size/same-timestamp source edits, changed package/analyzer inputs, project switching, worker eviction, independent cache recovery and output/hash comparisons against a clean build. A separate prepared-Restore action could remove repeated Restore work, but must retain project-specific SDK and NuGet semantics. Stable paths or direct references alone do not remove the dominant broad-edit latency in this graph.
