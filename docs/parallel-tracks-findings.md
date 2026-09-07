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
revision now passes, advancing the `local` join.

## Integration validation

Native macOS package-free cache acceptance passes all 8 tests, including
producer-free relocation and complete recovered-bundle hash/permission comparison.
The pinned environment check also passes. The branch is published as `codex/ready-tracks`; integrated native Linux
validation passes at `c384671`.

At `f22153c`, the integrated exporter passed 12 tests, runner contracts passed,
graph execution/rejection passed 16 tests, and forced multi-language recovery
passed its acceptance test. Handoff found one fixture-environment issue: reused
MSBuild workers changed NuGet config paths between the conditional-edge baseline
and regenerated build. The fix uses a dedicated CLI home for every preparation child and disables
worker reuse. The conditional regression passed in integration (25.276 seconds),
and runner contracts immediately followed by all six discovery tests passed in
the handoff worktree (93.889 seconds). The four direct handoff tests had already
passed in integration. No production behavior changed in this test-helper fix. Logs are retained in
`artifacts/parallel-regression` in the integration worktree.

## Accepted R01 integration

Revision `c384671006cba9527ca0fd72ce7af2cc17926c4d` passed the
[Linux graph execution and multi-language lane](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34070855043),
[repository setup lane](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34070855046)
and [Nix lane](https://github.com/keegan-caruso/msbuild-bazel/actions/runs/34070855061).
Setup ran 15 e2e tests with one expected native-runtime opt-in skip and passed the
focused binary-package regression. Nix ran all 15 tests, including native runtime
closure, without skips. These runs include the review fixes for canonical export
requests and per-child MSBuild worker isolation.

Together with the macOS evidence above, this accepts the package-free R01 local
baseline. R02 package execution is a separate gate. Multi-language composition
and recovery passed on both platforms, but this does not qualify Aspire or the
broader harness extensions. Local disk-cache relocation does not establish
independent remote-worker correctness or full host closure.
