# First parallel roadmap batch

The ready work packages were executed in separate worktrees from `6a14e1f`:
`linux`, `cache`, `handoff`, and `languages`. Integration uses
`codex/ready-tracks`; existing worktrees and main are preserved.

- Linux validation recovered passing current-baseline native CI evidence and
  adds the new controls to CI; see [graph execution findings](graph-execution-findings.md).
- Package-free cache acceptance implements independent mutations, graph-edge
  analysis and deleted-output/producer relocation controls;
  see [cache findings](graph-cache-findings.md).
- Replay/discovery controls re-evaluate manifests, publish plans atomically and
  reject incomplete graph bundles; see [handoff findings](graph-handoff-findings.md).
- The [multi-language harness](multilanguage-findings.md) composes existing
  Python/TypeScript rules with the generated .NET graph and checks local edits.

These are correctness experiments run with overlapping work, not performance
measurements. Package-bearing acceptance remains separately pending in
`tests/graph_cache_full`. R02 and later gates do not become accepted merely
because code for the first batch exists. Native Linux acceptance of the combined
revision is required before advancing the `local` join.

## Integration validation

Native macOS package-free cache acceptance passes all 8 tests, including
producer-free relocation and complete recovered-bundle hash/permission comparison.
The pinned environment check also passes. Combined regression and Linux results
are recorded below when their runs finish.

At `f22153c`, the integrated exporter passed 12 tests, runner contracts passed,
graph execution/rejection passed 16 tests, and forced multi-language recovery
passed its acceptance test. Handoff found one fixture-environment issue: reused
MSBuild workers changed NuGet config paths between the conditional-edge baseline
and regenerated build. This is being fixed with a dedicated CLI home and worker
reuse disabled; the final handoff rerun remains required. Logs are retained in
`artifacts/parallel-regression` in the integration worktree.
