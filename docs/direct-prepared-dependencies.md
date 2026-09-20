# Direct prepared dependencies

Project actions now consume prepared reference assemblies, analyzers, runtime
contracts and SDK metadata from their declared dependency bundles. The normal
MSBuild/SDK build of the consumer is retained. Recorded dependency target results
still answer SDK queries for frameworks, copy items, native manifests, static web
assets and Orchard module information; dependencies do not import their SDKs or
compile again.

`msbuild_compile_project` enables `direct_dependencies` by default. The owned
workflow also defaults `direct-dependencies` to true for project actions. Set it
to false to use the previous full-staging path. The lower-level portable runner's
`directDependencies` request field is explicit, allowing controlled comparisons.

## What changed

- Build one dependency placement plan from validated artifact indices. Cache each
  producer's artifact index/framework and each project's dependency closure.
  Pass that plan into the compilation session instead of reconstructing it for
  every dependency replay.
- Rewrite exact file paths in recorded SDK target items/metadata to their prepared
  inputs. Keep the producer's directory layout for adjacent-file resolution by
  MSBuild's assembly resolver and analyzer loader.
- When a transitive runtime contract already matches its current producer's
  verified hash, consume the existing prepared copy. Avoid copying it back into
  every intermediate dependency output directory.
- Materialize only SDK manifests whose contents require workspace-path rebasing,
  plus producer trees that need genuinely different current-runtime substitutions
  (so adjacent-file lookup cannot load stale bytes). Keep SDK hash
  recomputation for static-web-asset manifests.
- Normalize prepared paths back to the existing portable result contract before
  capture. Preserve MSBuild's literal path escaping, including percent signs,
  semicolons, dollar signs and item/property-expression characters. See the
  [MSBuild escaping contract](https://learn.microsoft.com/en-us/visualstudio/msbuild/msbuild-special-characters).

Input validation and publication seals remain in place. Ambiguous artifact
ownership and dependency cycles fail closed. This change does not replace SDK
metadata with guessed reference lists or invoke csc directly.

## Persistent compiler correctness

Direct compiler/analyzer inputs need stable **content-versioned** paths. A stable
filename with changed bytes and unchanged timestamps/sizes could otherwise leave
Roslyn's metadata/analyzer cache stale.

The Linux broker exposes each declared dependency/package tree through a path
keyed by all its declared file identities. The same tree has the same path across
consumer actions; a changed tree has a different path. Aliases stay inside the
read-only mount and expose only the current request's inputs. The private CAS is
not mounted. Ordinary source/preparation inputs and the writable workspace retain
whole-request versioning. Overlapping prepared groups are rejected.

## Orchard measurement

[Evidence](direct-prepared-dependencies-evidence.json) compares the retained
202-project Orchard graph's web entry action (201 dependency bundles) and a theme
action on macOS ARM64, pinned .NET 10.0.400. Each action uses the same source,
prepared inputs, output paths and full publication validation. Runs alternate
staged/direct/direct/staged, with no concurrent benchmark. Compiler reuse is off
in this comparison, isolating dependency preparation from the Linux worker gains.

| Action | Warm staged control | Direct runs | Reduction vs warm control |
|---|---:|---:|---:|
| OrchardCore.Cms.Web | 16.080s | 14.008s, 14.004s | 12.9% |
| TheBlogTheme | 2.495s | 2.314s, 2.338s | 6.8% |

The initial staged web sample was 18.834s. The table uses the later, warmer
16.080s control rather than attributing filesystem warming to the optimization.
A final pair after the adjacent-runtime/escaping safeguards confirmed **15.952s
staged → 13.992s direct (12.3%)**, again with identical files. A preceding parity
check took 17.419s with cold source/package validation (5.086s versus 2.494s in
the earlier warm direct run); its dependency restore phase remained 0.212s.
All samples are retained in the evidence rather than treating that I/O variation
as a change in the optimization's benefit.

All **6,932 published web bundle/API/runtime files** matched byte for byte across
all four runs. Theme outputs also matched completely.

For the web action:

- Dependency files staged: **11,799 → 754** (93.6% fewer).
- The remaining 754 are workspace-bearing static-web-asset JSON manifests.
- Dependency restore phase: **1.763s → 0.198–0.201s**.
- MSBuild phase: **8.000s → 6.172–6.201s**.
- Parent dependency-plan/replay setup: **0.030s → 0.070–0.076s**.

For the theme, staging falls from 766 files to 5 SDK manifests. These are isolated
project-action measurements, **not a new full-graph cold-build result or raw
MSBuild comparison**. Do not multiply them by the earlier worker speedups.

Reproduce with `tests/remote_workers/prepared_dependencies_probe.py`, supplying
`--execroot`, `--output`, `--dotnet`, `--runner` and optionally `--projects`.
The measured retained inputs were under
`/private/tmp/readonly-packages-orchard/state/b/execroot/_main`; complete logs and
binlogs are under `/private/tmp/direct-inputs-orchard-probe2`.

## Correctness and integration

The Linux compiler-worker qualification passes with:

- staged/direct/fresh output parity for an ordinary reference and real source generator;
- corrupted dependency rejection, changed API rejection by a stale consumer,
  and corrected-consumer parity with fresh compilation;
- a generator body change with equal assembly size and normalized timestamps;
- analyzer bundle paths containing literal `;`, `$()`, and `@` characters;
- identical prepared-tree paths across separate Bazel consumer actions, and a
  changed analyzer path while an unchanged ordinary dependency keeps its path;
- input-write, undeclared-read, previous-input, network and digest controls;
- graceful store cleanup and producer-state-deleted HTTP action-cache recovery.

The generated macOS owned-workflow acceptance also passes with Newtonsoft.Json,
PolySharp, borrowed package inputs and sparse package-origin bundles. Deleting
the producer leaves remote recovery with zero compilation and zero package
payload materialization. A dependency body edit and an entry edit each compile
one project; invalid publication controls continue to reject uploads.

Owned tooling/style checks, ActionRunner contract tests and 105 Python checks
passed in Linux (three macOS-specific checks skipped). The ActionRunner suite
also passed on macOS, including literal-path replay and unknown-target rejection.
No GitHub CI ran. The existing Linux owned-workflow controller limitation remains;
the persistent worker is exercised through actual Bazel worker actions, while
the owned workflow integration is qualified on macOS.
