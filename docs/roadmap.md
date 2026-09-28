# Planned work

The next performance priority is **API edits** across larger, more varied
graphs. Cold builds still matter. We will judge progress mainly by body and
API edits and by recovery from an independent remote cache. See
[current support](implementation-plan.md) for qualified behavior and
[performance](performance.md) for measured baselines.

## Completed generated-graph sequence

The original eight-stage plan began at `d4a64b4`. Its outcomes and limits are
recorded in the stage reports; these are completed slices, not claims that every
.NET repository is supported.

| Stage | Result |
| --- | --- |
| 1–2. Generate complete HTTP and Immutable graphs | [44 HTTP projects](project-sync-http-full.md) and [36 Immutable projects](project-sync-immutable-full.md) |
| 3. Recover from HTTP cache | [Independent consumer and edit controls](project-sync-remote-cache.md) |
| 4. Simplify configuration | [Shared defaults and diagnostics](project-sync-defaults.md) |
| 5. Qualify larger graphs | [Generated Orchard and Avalonia slices](project-sync-broader-graphs.md) |
| 6. Validate project changes | [Mutation, repair and invalidation controls](project-sync-mutations.md) |
| 7. Measure workflow costs | [Paired raw/Bazel results](project-sync-workflow-costs.md) |
| 8. Prepare adoption | [Quickstart and independent consumers](adoption.md) |

The original acceptance checklist is preserved in the
[pre-condensation roadmap](https://github.com/keegan-caruso/msbuild-bazel/blob/4ab387c59ddf5fda46d15646cf0f738d9a0026a0/docs/roadmap.md).

### 9. Improve incremental API edits across a broader scenario matrix

**In progress.** The [reference-boundary matrix](reference-invalidation.md)
proved the B→C boundary in small graphs. The
[Orchard follow-up](orchard-reference-boundaries.md) found that a broad API
addition still compiled 193 projects, with content-dependent asset paths
changing 87 reference assemblies. The original paired Orchard sample took
132.755 s in Bazel versus 27.537 s in raw MSBuild (4.82×); a later paired
follow-up measured 154.178 s versus 29.798 s. These are specific cases, not a
general API-edit ratio. Body edits remain much faster in those samples.

Next, sample leaf, intermediate and widely shared projects in synthetic and
qualified Orchard, Avalonia, ASP.NET Core and runtime slices. Include narrow
chains and broad fan-out, public additions/removals, signature changes,
internal/friend changes and an API edit that stops propagating when the middle
project's reference stays stable. Check deliberately failing callers, repair,
revert and dependent test behavior. Compare the same build/test scope with raw
MSBuild under fixed pins and resource limits.

For each retained scenario, alternate build order and take at least three
samples. Report median/range, compile counts, reference changes, cache hits,
worker reuse, evaluation/staging/transfer time and memory pressure. Separate
warm-local edits, fresh remote-cache consumers and cache reversion. Profile
repeatable gaps and remove unnecessary invalidation before optimizing necessary
work. Prove a fix in a small synthetic, then rerun the large-graph matrix and
cache/test controls. Do not collapse different edits into one speedup number.

The proposed gate is **under 2× raw** for expensive qualified API edits while
preserving the body-edit advantage. It has **not** been achieved across the
matrix. Completion requires an explained scenario set, meaningful improvement,
correctness controls and explicit remaining gaps.

## Other qualification tracks

- Cold builds: resume from the [memory-budgeted profile](runtime-cold-timing.md).
  Do not compare older runs across different VM resources or cache states.
- Stable project paths and direct references: the
  [synthetic prototype](stable-project-paths.md) is off by default; its broader
  [design](stable-project-paths-design.md) still needs package/task/analyzer,
  remote-cache and real-graph qualification.
- Runtime and SDK source builds: see [runtime workflow](runtime-workflow.md)
  and [SDK source graph](source-sdk.md). Reproducibility, full cold comparison,
  remote execution and unqualified runtime products remain open.
- Platform/workload breadth: Linux x64, macOS x64, Windows, coverage, Pack,
  Publish, wider Native AOT, NBGV, WASM and IDE workflows need separate
  qualification. The [platform limits](platform-validation-scope.md) and
  [live issues](https://github.com/keegan-caruso/msbuild-bazel/issues) provide
  their current scope; this list is not a tracker-status snapshot.

Keep production rules generic, MSBuild SDK compilation intact and custom inputs
explicit. Validate both supported Bazel versions before claiming compatibility.
Distinguish artifact recovery from test execution, installed-runtime results
from source-built-host results, and HTTP caching from remote execution. CI is
manual-only.
