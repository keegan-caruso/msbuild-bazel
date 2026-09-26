# Generated Orchard and Avalonia graphs

Stage 5 of the [roadmap](roadmap.md) expands production synchronization to two
existing authored qualification graphs. The production rules contain no Orchard
or Avalonia project names. Repository-specific contracts belong to the fixtures.

Baseline: Linux ARM64, SDK 10.0.400, Bazel 9.2.0, Release. Orchard is pinned to
`04467a3438d4255627c1a478598a1585b3ff2947`; Avalonia to
`37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0`, with pinned submodules.

## Graph boundaries

| Graph | Generated configured projects | Source project paths | Selected entry points |
| --- | ---: | ---: | ---: |
| Orchard CMS | 202 | 202 | 1 |
| Avalonia | 53 | 40 | 13 |

The comparison drivers check configured nodes, compile inputs, package privacy and
dependency roles against the independently authored inventories. Avalonia also
checks compiler item inputs, including package-generated AdditionalFiles.
Compilation declarations come from `msbuild_sync`; fixture code retains package
acquisition, explicit generators, tool bindings, runtime inputs and test contracts.
Two Avalonia tools compile in both target and execution configurations, giving
55 compilation actions for its 53 configured project declarations.

This qualifies the selected Avalonia desktop, controls, font, headless and test
closure on Linux. It does not qualify running a Windows/macOS desktop application,
all of Avalonia, or platform-native deployment. Orchard qualification renders a
fresh setup page and checks three embedded assets; it is not a full CMS test suite.

## Recorded Orchard results

All 202 generated configurations build. The setup page and three embedded assets
match the raw build's HTTP status/content types; the three static assets also match
byte-for-byte. Dynamic antiforgery HTML is not treated as a deterministic hash.
Translations are included through the declared generated-directory mapping.

Body/API/CSS edits rebuild 1/193/4 assemblies, with zero compilations after each
revert. CSS changes the Setup module's reference metadata and therefore rebuilds
its two application-target consumers and the web application, matching the
[authored graph's behavior](orchard-explicit-performance.md). Edited CSS is served
with the exact input hash. Missing-source detection preserves generated output,
and repair restores a successful sync check. Body/API and resource controls were
recorded in separate runs; an initial harness assertion incorrectly expected CSS
to preserve the module reference.

The stopped-producer consumer independently acquires 287 archives (454,042,134
bytes), recovers **491/491 build actions** remotely, and matches **4,528 output
hashes**. These comprise 202 compilations, 287 package extractions, the build runner
and SDK host. A fresh four-endpoint HTTP smoke run and relocated `sync --check`
pass. This is application execution, not a Bazel test-cache claim.

## Recorded Avalonia results

All five suites match raw MSBuild exactly: **5,882 passes and 42 skips**.
The generated graph preserves all 55 configured reference outputs, embedded
resource names/bytes/order, compiled XAML methods and five IDL outputs, subject to
the narrow COM-name comparison below.

Body/API/XAML/IDL edits execute 2/43/2/3 build actions respectively. Every revert
executes zero build actions. Fresh tests retain the raw outcomes, and missing-source
checks preserve the last generated file before successful repair.

The producer-stopped consumer independently acquires 194 archives (357,743,692
bytes), recovers **291/291 build/test actions** remotely, and matches **5,356 output
hashes**. Those actions include 55 compilations, 224 package extractions, five
IDL generations, five tests, the build runner and SDK host. Forced test execution
also passes; relocated `sync --check` reuses its declared tools from cache.

All six new small acceptance fixtures pass on both Bazel 8.8.0 and 9.2.0. Owned-code
checks pass: 5 style, 7 tool, 36 runner and 50 sync/name tests. The full upstream
qualification remains scoped to Bazel 9.2.0.

## Generic behavior exercised

- **Per-project and per-framework package sets.** One sync target can declare
  multiple closed locks. `packageLock` and `frameworkOverrides` select the correct
  set, properties, dependencies and tool bindings for each configured node.
- **SDK and custom file inputs.** Web/Razor SDK projects retain framework references.
  `inputItems` declares reviewed file kinds and metadata; `exportTargets` declares
  target-result contracts. Package-generated files that local evaluation cannot
  discover stay explicit item bindings.
- **Source-relative generated directories.** A reviewed MSBuild target may write
  beneath an explicitly mapped directory. The runner redirects that directory to
  writable action state and publishes it beneath the runtime output. Orchard's
  translation copy uses this contract. Inputs remain read-only; overlaps, runtime
  collisions and generated symlinks are rejected.
- **NuGet replay.** Preserve private project edges and original package version
  requests. The latter lets NuGet apply SDK package pruning. Central transitive
  pinning uses the closed package graph without turning late implicit SDK packages
  into authored central versions. Each retained target framework has a distinct
  restore item identity, so NuGet's duplicate removal cannot discard a variant.
- **Evaluation order and test outputs.** Preserve MSBuild compile/resource item
  order. Explicit test output type and apphost choices reproduce package changes
  that occur after local evaluation.
- **Generated Starlark literals.** Output preserves Unicode and literal escapes in
  source paths and properties. JSON string escaping is not used as Starlark syntax.
  Implicit NETCore/NETStandard framework references are not propagated as explicit
  transitive framework requirements.

These changes retain closed package validation and explicit assembly selection.
They do not permit undeclared downloads inside build actions or arbitrary target
execution during synchronization.

## Reproduction and evidence

Prepare the pinned authored inventories with the existing
[Orchard](orchard-explicit-compatibility.md) and [Avalonia](avalonia-expanded.md)
qualification drivers. The mapping drivers consume those independent inventories:

```sh
python3 tests/project_sync/upstream/orchard.py WORKSPACE EVALUATION_JSON RESTORED_SOURCE
python3 tests/project_sync/upstream/avalonia.py PREPARED WORKSPACE
```

The initial Avalonia pass retains authored evaluation tools. Run `bazel run //:sync`,
then rerun its mapping driver with `--generated` to replace all project declarations
with aliases to production-generated targets. Run sync again and `--check`.
Keep Avalonia source under `upstream/`: its source directory named `external/`
otherwise conflicts with Bazel's execution-root repository directory.

Use `compare_orchard.py` and `compare_avalonia.py` for graph comparisons;
`avalonia_qualify.py` compares all five test suites, reference assemblies, embedded
resources, XAML methods and five IDL outputs against raw MSBuild.
The existing Desktop COM exception remains: only the 53 private file-local type
name hashes in `Avalonia.Win32.Automation` are normalized for raw metadata
comparison. All other reference assemblies require byte equality. Independent
cache recovery requires exact producer bytes for every assembly, including COM.
`orchard_controls.py` and `avalonia_controls.py` exercise edits and restoration.

`remote_graph.py --family orchard|avalonia` uses the independent-cache procedure in
[stage 3](project-sync-remote-cache.md). The Avalonia raw argument is its qualification
JSON; Orchard uses its raw smoke JSON. Transfer declared workspace inputs only,
independently acquire pinned archives, stop the producer, and recover at a different
path in an empty consumer. Cache recovery and forced test execution are distinct
checks. Orchard uses an actual HTTP smoke run rather than a cached test claim.

Small acceptance drivers under `tests/project_sync/` cover Web/Razor projects,
multiple locks, framework overrides, pruning, private restore edges, selected
frameworks and generated directories. Negative cases preserve generated files or
fail the build at the declared boundary; repair restores successful behavior.

[Compact evidence](project-sync-broader-graphs-evidence.json) records the completed
checks. Both Bazel versions also pass all 43 SDK-free analysis tests and execution
requirement checks on macOS ARM64. Toolchain/Starlark checks pass. No CI was dispatched.
Timing from these correctness runs is not a repeated performance baseline; stage 7
owns that comparison.
