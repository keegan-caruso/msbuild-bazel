# Planned work

The active priority is complete generated graphs, independent remote-cache recovery,
then developer experience and broader qualification. Stages 1–6 are **complete**;
stages 7–8 remain **planned**;
[current support](implementation-plan.md) records what is already measured.
This sequence starts from local commit `d4a64b4`, not an assertion that the work has
already reached `main`. Review and integrate the accumulated changes before basing
new work on a different branch.

## Starting point

The [latest qualification](project-sync-expanded.md) covers Linux ARM64,
SDK 10.0.400, Bazel 9.2.0, Release/net10.0:

| Graph | Generated assembly projects | Authored dependency producers | Test baseline |
| --- | ---: | ---: | ---: |
| Http.Abstractions | 2 of 44 | 42 | 714 passes, exact raw/Bazel names and outcomes |
| System.Collections.Immutable | 2 of 36 | 34 | 22,544 passes, documented display-name normalization |

Both have local test-cache reuse, body-edit invalidation, stable public references
and custom-document drift rejection. Immutable verifies its source-built assembly
inside the installed runtime host. These results do not establish full-graph
synchronization, independent remote recovery, remote execution or whole-repository
support. The combined qualification driver has not yet completed as a single fresh
run; the recorded stages used targeted retries.

## Ordered delivery plan

Work through these stages in order. Split a stage into reviewable changes when
needed, proving new behavior with a small synthetic before applying it upstream.
Keep the existing tests and explicit input boundaries intact throughout.

### 1. Generate the complete Http.Abstractions graph

**Complete:** [full graph and clean-driver evidence](project-sync-http-full.md).

**Depends on:** the starting baseline.

- Reproduce the current combined setup from fresh disposable checkouts; remove any
  remaining manual preparation steps from its driver.
- Inventory the 42 authored dependency producers by role and configured framework.
  Migrate ordinary libraries first, then test infrastructure and analyzer/tool
  projects. Identify nodes by project path plus global properties, not path alone.
- Generate project rules, sources and dependency edges through `msbuild_sync`.
  Preserve framework selection, private packages, bootstrap outputs, PublicAPI
  files, checked-in generated sources and the SDK-backed test host.
- Keep package acquisition, bootstrap/task contracts and deliberate provider
  composition authored. “Full graph” does not mean guessing custom task behavior.

**Done when:** all 44 current configured assembly producers come from production
sync, with no fixture script emitting their per-project compilation declarations
and no edits to generated `.bzl` output. A second sync produces no diff, `--check`
passes, all 714 raw/Bazel test outcomes match, and body-edit, API-edit, missing-input
and contract-drift controls pass. Record any intentional graph-count change.

### 2. Generate the complete Immutable graph

**Complete:** [full graph and clean-driver evidence](project-sync-immutable-full.md).

**Depends on:** stage 1's traversal and configured-node support.

- Migrate its 34 authored dependencies in small groups: reference projects,
  implementations, test utilities, analyzers and managed build tools.
- Preserve framework-specific tool edges, private dependencies, generated resources,
  reference/implementation pairs and explicit assembly selections. Retain the
  declared NativeAOT directive input without claiming NativeAOT execution.
- Reuse generic rule/mapping behavior; keep runtime-specific bindings in the
  qualification fixture. Keep the installed-host boundary unchanged for this stage.

**Done when:** all 36 current configured assembly producers are generated,
regeneration is stable, and all 22,544 normalized raw/Bazel outcomes match. The
loaded-assembly probe must identify the generated implementation before and after
a body edit. Reference stability, API invalidation, missing tool/input rejection
and ambiguous-assembly rejection must pass. Do not broaden normalization to hide
new differences.

### 3. Prove independent HTTP-cache recovery

**Complete:** [independent recovery and edit evidence](project-sync-remote-cache.md).

**Depends on:** stages 1–2.

- Seed a cache from a Linux producer for each complete generated graph. Record
  action counts, output hashes, test outcomes and the exact tool/configuration pins.
- Stop the producer. Use a second container with a different workspace path, empty
  Bazel output base, no local action/disk cache and no mounted producer outputs.
  Acquire declared repositories/packages separately and record that setup cost.
- Regenerate or consume the checked-in generated graph as the documented workflow
  requires; verify relocation does not change cache identities unnecessarily.
- Recover the build and test outputs, then force test execution using the recovered
  assemblies. Exercise one body edit, one API edit and one declared input change.

**Done when:** every expected cache-eligible build action is accounted for as a
remote hit or a documented, resolved exception; recovered output hashes match the
producer; both cached test recovery and fresh test execution pass. Edits invalidate
the affected actions without rebuilding unrelated branches. No undeclared SDK,
NuGet cache or producer filesystem supplies missing inputs. State any remaining
path sensitivity explicitly; remote caching does not qualify remote execution.

### 4. Simplify configuration and diagnostics

**Complete:** [defaults, diagnostics and equivalence evidence](project-sync-defaults.md).

**Depends on:** the concrete repetition and failures found in stages 1–3.

- Consolidate repeated mappings into reusable defaults where semantics are identical.
  Define override precedence and reject ambiguous or stale entries.
- Preserve the simple SDK/global.json entry point. Keep package identities, custom
  task inputs, runtime hosts and unusual assembly choices explicit.
- Report the project/configuration, offending item/import and required mapping when
  sync cannot proceed. Provide a small example of each supported customization.

**Done when:** representative ordinary apps and these complex graphs need less
repeated configuration, with before/after examples. Their generated action inputs
and behavior remain equivalent; unknown tasks, unsafe paths and conflicting
conditions still fail. Do not auto-approve custom-document hashes or discover
ambient tools to make configuration shorter.

### 5. Qualify broader real-world graphs

**Complete:** [generated Orchard/Avalonia graphs and independent recovery](project-sync-broader-graphs.md).

**Depends on:** stages 3–4.

1. Apply the generator to Orchard's already-qualified 202-project authored graph.
2. Apply it to the existing pinned Avalonia slices with XAML/IDL generation,
   analyzers, native inputs and tests; expand only after each slice passes.

Compare generated and authored configured nodes/edges before execution. Reuse the
existing raw-MSBuild baselines and edit/cache controls, retaining documented
upstream test-stability limits.

**Done when:** Orchard's covered graph and the named Avalonia slices are generated
without repository-specific production rules, retain their existing correctness
controls, and recover independently from cache. Report exactly which projects and
platforms were exercised; this is not a promise to build all of Avalonia.

### 6. Validate everyday project changes

**Complete:** [mutation, invalidation and repair evidence](project-sync-mutations.md).

**Depends on:** stages 4–5; small mutation fixtures may be developed earlier.

Exercise adding/removing projects, references and source files; changing frameworks,
conditions and shared props; upgrading packages; changing analyzer/task inputs;
and editing test data or runtime-host inputs. Include failure and repair paths.

**Done when:** one documented synchronization workflow updates the graph
predictably, `--check` detects stale declarations, failed sync preserves the last
valid output, and repeated sync is stable. Builds/tests use the correct updated
inputs, dependent tests rerun when required, and unrelated branches stay cached.
Reverting a change must recover the earlier graph and reusable outputs. Keep small
synthetics for each contract and representative mutations on the larger graphs.

### 7. Measure and reduce end-to-end workflow costs

**Depends on:** stable workflows from stages 3–6.

Measure acquisition, initial sync, unchanged sync, cold build, warm no-op, leaf body
edit, public API edit and independent remote recovery separately. Compare matching
build/test scopes with raw MSBuild on the same machine and configuration. Record
resource limits, repetitions and variation, action counts, transfer volume and
where wall time is spent.

**Done when:** the [performance report](performance.md) contains reproducible
comparisons and a ranked list of measured costs. Agree quantitative targets from
those baselines, then optimize the largest costs one change at a time. Prioritize
large graphs and remote-cache workflows; modest cold overhead is acceptable,
but a large unexplained regression is not. Recheck correctness after each change
and retain only meaningful measured improvements.

### 8. Prepare a coherent external adoption path

**Depends on:** stages 4–7.

- Make the primary quickstart use the supported SDK/global.json and sync workflow,
  with committed generated files and explicit examples for the unusual cases.
- Test it from a clean checkout without maintainer qualification scripts or ambient
  tools. Explain local development, build-server cache setup and support limits.
- Define API/version compatibility, upgrade guidance and the proposed source,
  runner-package and Bazel Central Registry distribution path.

**Done when:** an external developer can build/test the example and configure a
second cache consumer by following the docs alone. Links and examples agree with
current behavior, and the distribution/versioning proposal is reviewable.
This stage prepares adoption; it does not publish a release or change repository
visibility.

## Evidence and delivery rules

- Keep one worktree per change, commit logical steps, and review before integration.
  Record measured results beside their commands and pinned inputs; update this
  roadmap's status only when the stage's completion criteria are satisfied.
- Keep production rules generic and custom inputs explicit. MSBuild retains SDK
  compilation; sync evaluates locally and does not run arbitrary build targets.
- Use Linux ARM64 as the current execution baseline. Validate affected generic
  behavior against both supported Bazel versions before claiming compatibility;
  retain the exact version scope of each upstream qualification.
- Keep raw-test parity, body/API edits, stable public contracts and missing-input
  rejection as continuing controls. Record artifact recovery separately from test
  cache hits, and installed-runtime evidence separately from source-built hosts.
- CI remains manual-only. Reuse disposable containers, preserve compact evidence,
  and retire task-owned build state when no longer needed.

## Other work, outside this sequence

- Cold-build optimization remains tracked by [#13](https://github.com/keegan-caruso/msbuild-bazel/issues/13).
  Resume from [the recorded measurements](runtime-cold-timing.md) during stage 7;
  do not treat an older single-VM result as the new generated workflow's baseline.
- The first authored JIT test remains a separate slice under
  [#74](https://github.com/keegan-caruso/msbuild-bazel/issues/74), with its
  [bootstrap boundary](runtime-jit-bootstrap.md).
- Wider remote execution and a second executor platform remain separate from
  HTTP-cache recovery: [#43](https://github.com/keegan-caruso/msbuild-bazel/issues/43),
  [#44](https://github.com/keegan-caruso/msbuild-bazel/issues/44),
  [current qualification](remote-execution.md).
- Source-dependent test relocation remains tracked by
  [#9](https://github.com/keegan-caruso/msbuild-bazel/issues/9); reuse stage 3's
  path controls when addressing the [remaining test boundaries](bazel-test.md).
- Diagnose the macOS out-of-process MSBuild task-host failure as a separate
  compatibility track. Preserve sandboxing; it does not block Linux qualification.
- Public source and release distribution are separate. Keep the
  [publication report](publication-readiness.md) as historical preparation evidence;
  stage 8 owns the new distribution proposal.

Issue links above and below are existing references, not a fresh tracker-status audit.

## Separate qualification tracks

- Native Linux x64 [#56](https://github.com/keegan-caruso/msbuild-bazel/issues/56),
  macOS x64 [#54](https://github.com/keegan-caruso/msbuild-bazel/issues/54), and Windows
  [ARM64 #61](https://github.com/keegan-caruso/msbuild-bazel/issues/61) /
  [x64 #62](https://github.com/keegan-caruso/msbuild-bazel/issues/62).
  Windows also needs a runner sandbox implementation.
- Instrumented coverage [#23](https://github.com/keegan-caruso/msbuild-bazel/issues/23),
  Pack [#25](https://github.com/keegan-caruso/msbuild-bazel/issues/25),
  Publish [#29](https://github.com/keegan-caruso/msbuild-bazel/issues/29), and
  NativeAOT [#32](https://github.com/keegan-caruso/msbuild-bazel/issues/32).
- NBGV production context [#27](https://github.com/keegan-caruso/msbuild-bazel/issues/27),
  wider restore metadata [#28](https://github.com/keegan-caruso/msbuild-bazel/issues/28),
  Blazor/WASM [#37](https://github.com/keegan-caruso/msbuild-bazel/issues/37), desktop and
  languages [#38](https://github.com/keegan-caruso/msbuild-bazel/issues/38), Aspire
  [#40](https://github.com/keegan-caruso/msbuild-bazel/issues/40), and IDE workflows
  [#45](https://github.com/keegan-caruso/msbuild-bazel/issues/45).

The retired milestone system is preserved in [history](history.md).
