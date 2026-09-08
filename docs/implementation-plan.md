# MSBuild / Bazel implementation plan

## Question

Can Bazel cache and schedule configured .NET projects while each action uses MSBuild and consumes dependency artifacts plus MSBuild result metadata?

## Bazel version selection experiment

The [Nix Bazel matrix](nix-bazel-matrix-findings.md) adds selectable official
7.7.1, 8.4.2, 8.8.0 and 9.2.0 binaries on macOS ARM64, holding the SDK fixed.
The [layout follow-up](nix-bazel-layout-findings.md) uses native wrapper defaults,
separate test state and selected-version checks to reach the compatibility gates.
All four selected versions pass the focused native macOS checks, repository
tests and explicit sandbox/cache probe. Further failures are recorded without
adapter compatibility fixes. This is a
focused R17 experiment, not qualification of the full supported-version/platform matrix.

## Current status and next step

Repository-owned .NET tooling and unit tests now have [build-enforced code style
and warning policies](code-style-findings.md), separate from fixture build semantics.

The added R01 [Starlark baseline](starlark-core-findings.md) now passes on native
macOS and local Linux ARM64: pinned formatting/lint, rule analysis, prepared-workspace and repository
controls, with cache/discovery/forced-replay regressions retained. The additional
`starlark_packages`, `starlark_configured` and `starlark_tests` gates now pass
[native macOS qualification](r02-r04-validation-findings.md), including generated
workspaces, real generator-version changes and cold/recovered reference consumers.
The [R05a generator/reference-role slice](r05a-findings.md) implements project and
package generator combinations, diagnostic-only analyzers and recovered consumer
compilation. The [selected Spectre.Console graph](spectre-acceptance-findings.md) now passes native macOS mutation and relocated-cache acceptance. R09 preparation
reuse starts from the accepted R04 measurements and discovery/package contracts;
compile-interface optimization follows the relevant R05/R06 role contracts.
Broader R03 entry points and independent-worker gates remain separate. See the
[active execution order](roadmap.md#active-execution-order).

The three parallel [upstream test tracks](serilog-test-plan.md) now pass [native macOS acceptance](serilog-test-acceptance-findings.md): unchanged Serilog approval Build/Test, exact failure controls, test-data-only invalidation, and producer-free relocated build recovery followed by actual test execution. The [selected-framework adaptation](selected-framework-findings.md) preserves ordinary SDK reference selection without changing project declarations.

Further Linux validation is deferred by request. The [R04 selected Serilog library](r04-integration-findings.md) now passes native
macOS mutation and relocated-cache acceptance after R02 and selected R03; see
[active platform scope](platform-validation-scope.md). Historical platform
evidence below remains bounded to its recorded source and experiment.

Steps 1–7 below are implemented. The two-target Bazel adapter also has
[action-identity](action-identity-findings.md) and
[pinned build-package](package-input-findings.md) acceptance coverage on macOS
ARM64. The earlier nine-test suite, including replay and native sandbox/cache
cases, also passed in Ubuntu 22.04 Linux x86-64 CI; see [Linux evidence](bazel-findings.md#ci-repair-2026-09-05).
Linux validation is prepared as one manual quick/full workflow, with Nix separate; see the [CI scope and local validation record](ci-scope.md).
Cross-platform artifact reuse remains unproven.

The first staging slice now compares identical consumer bundles across fresh
native macOS ARM64 executions; see [staging findings](staging-findings.md).
The first [native runtime slice](native-runtime-findings.md) now declares the Nix
reference closure and rejects incomplete declarations. The [.NET runner](dotnet-runner-findings.md)
removes Python from build actions while retaining the Python experiment harness.
The [runner refactor](action-runner-refactor.md) moves policy into declared MSBuild
imports and strengthens the .NET request/process contracts.
The [runtime integrity extension](native-runtime-integrity-findings.md) adds
payload hashes, copied-library rejection/invalidation and loader diagnostics.
The [loaded JIT experiment](loader-runtime-findings.md) now forces one substituted
native library into the actual MSBuild runtime, with loader evidence and
invalid-image rejection. Full runtime closure and general host-read discovery
remain open. Managed package DLL/runtime assets and transitive handoff now pass
focused Linux native-sandbox acceptance. The local-only graph exporter
(step 8) now has passing Linux acceptance [evidence](graph-export-findings.md).
The first [generated graph execution slice](graph-execution-findings.md) now
passes native macOS acceptance for a Release/net10.0 package-free diamond.
R02 [managed package execution](graph-package-plan.md) now has native macOS
cache and PrivateAssets evidence; its combined Linux qualification is pending.
Broader configurations remain open.

The managed binary-package milestone has a test-first
[contract](binary-package-plan.md), fixture and probe. Its
[validation record](binary-package-findings.md) includes passing native sandbox,
cache, relocation, upgrade and rejection evidence. Broader NuGet behavior is
still outside this measured boundary.

## SDK baseline refresh

The SDK 10.0.400 upgrade passes the targeted native macOS regression gates, separately from R09 preparation reuse.
See [SDK upgrade findings](sdk-upgrade-findings.md) for pins, validation and the original
Spectre prerequisites. Historical results below retain their original SDK scope.

The [Spectre framework prerequisite](spectre-framework-findings.md) extends selected
framework identity handling to netstandard2.0 and is now integrated into the
[selected real-project acceptance](spectre-acceptance-findings.md).
The [ordinary Spectre baseline](spectre-baseline-findings.md) now records the
selected net10.0/netstandard2.0 graph, generated API oracle and Git identity
requirements; the adapter comparison is recorded in the integration findings.

## Upstream issue coverage

The [language-rule lessons](language-rule-lessons.md) compare Java, Scala, Python,
TypeScript, Go and Rust designs with the MSBuild-retention goal. Their preparation
and dependency-role lessons are scheduled in the roadmap and dependency graph;
the proposed optimizations remain unqualified until their acceptance gates pass.

The [rules_dotnet issue review](rules-dotnet-issue-plan.md) maps the current open
board to milestone owners and turns selected closed fixes into regression gates.
It includes the full dated issue inventory, next-batch priorities and explicit
scope decisions. This is research/planning evidence; upstream repros were not run.

## Forward roadmap

The [forward roadmap](roadmap.md) starts at the implemented generated-graph slice
and uses R01–R17 for local correctness, package/configuration support, Serilog,
specialized project tracks, independent remote workers and the supported-adapter
endpoint. Near-term milestones have concrete deliverables and exit gates; later
tracks are refined before implementation. Historical milestone numbers in older
contracts and findings remain unchanged; the roadmap includes their mapping.

Current macOS evidence covers R01 cache/replay/discovery, the selected R02 managed-package and R03 configured-node slices, and the R04 Serilog library plus unchanged approval test, with their additional rule/generated-workspace gates. [Repeated comparative measurements](serilog-performance-findings.md) now pass all 24 correctness/work-set samples; they show adapter overhead for this two-project graph and do not qualify useful performance at scale. R09 preparation reuse is next. R05a generator/reference-role evidence is tracked in [its findings](r05a-findings.md); broader R03 entry points and Linux validation remain separate. The [coverage matrix](scenario-coverage.md) and
[pinned project selections](coverage-project-selections.md) define the broader
portfolio and separate proposed work from measured support. The
[parallel dependency graph](roadmap-graph.md) splits milestones into work packages
and records the acceptance gates between independent tracks. The
[first parallel batch](parallel-tracks-findings.md) records execution and
integration of the four initially ready work packages.

## Milestone sequence

1. Add Shared and App SDK projects, with App referencing Shared, and a Microsoft.Build.Traversal entry point. Pin Traversal when introduced.
2. Establish a normal Release traversal/static-graph build baseline and confirm project isolation.
3. Build Shared separately; stage its artifacts and result cache; build App with the input result cache. Verify Shared compilation does not execute again.
4. Repeat with clean directories and changed checkout/action paths. Investigate absolute paths in result metadata before claiming portable caching.
5. Prove relocated dependency-result replay through public MSBuild project-cache APIs, using a versioned metadata payload and separately staged artifacts. Keep the raw-cache path probe as a control. See the [replay experiment](result-replay-plan.md) for the proposed contract and acceptance cases.
6. After replay works, define the Bazel e2e harness and add a custom rule and runner for these two explicit targets. Keep restore/tool acquisition outside compilation actions; test separate action paths and sandbox inputs explicitly.
7. Measure cold build, unchanged rebuild, App-only edit, Shared edit, and reuse after clearing local outputs while retaining the Bazel disk cache. Assert which actions execute and verify application output.
8. Only after the handoff works, add a general C# ProjectGraph exporter and custom MSBuild targets for input/output contracts. The replay experiment may use ProjectGraph for the two-project fixture without expanding into a general exporter.

## Acceptance evidence

The [validation strategy](validation.md) maps these requirements to Bazel analysis
tests, real-build integration, existing findings and planned acceptance gates.
Use its evidence checklist when recording a new result. The roadmap now assigns
these checks to [milestone deliverables and exit gates](roadmap.md#validation-ownership-and-remaining-gates),
with open Starlark baseline/package/configuration/test work and release version
qualification recorded in the dependency graph; earlier acceptance remains scoped
to its original evidence.

- Plain MSBuild and Bazel-built App have equivalent observable output.
- App-only changes reuse Shared's Bazel action output.
- Shared changes invalidate dependent work correctly.
- Dependency builds are not silently repeated inside downstream actions.
- Results do not depend on pre-existing bin/obj or an undeclared user NuGet cache.
- SDK, package assets, configuration, imports, and custom inputs participate in action identity.

## Scope

One framework, Release, local execution and local disk cache. Linux x86-64 was
the initial platform target; current measured platform evidence is stated above. Remote execution, cross-platform support, multi-targeting, Native AOT, publishing, Razor/WPF, and arbitrary NuGet build targets need separate evidence. Pinned bootstrap tools alone do not make build actions hermetic.

## Recorded results

The [Apple container runbook](apple-container-runbook.md) covers host setup,
the Shared -> App smoke test, and the focused Bazel sandbox/cache probe on an
Apple silicon Mac. It includes required guest protected-path settings,
troubleshooting, cleanup, and the limits of this local validation.

Codex setup and CI are established. The initial process contract and six e2e scenarios were committed before implementation. See [e2e scope](e2e-scope.md), [interfaces](interfaces.md), and [findings](findings.md).

Step 4 now has a runnable path probe and a seventh e2e test. On macOS ARM64 with
the pinned Nix SDK, moving the bundle preserves App-only compilation, but moving
the project workspace causes raw MSBuild `MSB4252` at `GetTargetFrameworks`. A
fresh dependency cache at the new path succeeds. See [path findings](path-findings.md)
for commands, controls, and limitations. Raw-cache relocation remains unsupported.

Step 5 now has a public-API replay plugin, an independent probe, and black-box
acceptance coverage. Relocated Build, App-only edit, and narrow Publish succeeded
on macOS ARM64 after deleting the producer, with strict isolation and no Shared
compilation. See [replay findings](replay-findings.md).

Steps 6 and 7 now have an explicit two-target Bazel rule, Shared-only producer,
App dependency replay, and a native sandbox/cache harness. Cold, unchanged,
App edit, Shared edit, cleared-output disk-cache reuse, and a fresh Bazel output
base are measured on macOS ARM64. See [Bazel findings](bazel-findings.md) and the
[process contract](bazel-interface.md). Subsequent input-identity experiments
are recorded below.

The first action-identity hardening experiment now covers imported targets,
generated-source data, declared versus ambient environment, App restore metadata
and host-identity changes. Python runtime files are declared; direct isolated
Python execution replaces the shell launcher, and remote execution/cache use is
disabled. See [identity findings](action-identity-findings.md). The following
package experiment extends that input boundary.

The pinned package-input experiment now stages verified archive payloads using
per-project restore manifests. Package data and target upgrades rebuild Shared
and App; missing, corrupt and stale-version inputs fail before compilation.
See [package findings](package-input-findings.md). This is build-only package
coverage, with no binary/runtime assets or arbitrary package closure claim.
See the current status above for remaining work.

The [staging experiment](staging-findings.md) separates diagnostic outputs from
consumer bundles, maps compiler paths and narrows Shared's intermediate handoff
to the reference assembly. A fresh output base with an empty cache forces real
executions and compares all bundle bytes and executable bits. Runtime closure
and broader output discovery remain open.

The next parallel slices are tracked in [configured-node findings](configured-node-findings.md)
and [lifecycle findings](lifecycle-findings.md). Their ordinary MSBuild controls
retain the observed isolation failures explicitly; implementation and native
acceptance states are recorded separately from those baselines.

The [synthetic scale protocol](synthetic-scale-findings.md) has a measured
ten-node fan slice and a corrected thousand-node preparation recursion failure;
larger native runs and aggregate memory remain unmeasured. The
[Serilog input oracle](serilog-inputs-findings.md) records pinned ordinary SDK
behavior while adapter generator/signing support remains a separate gate.

The [consumer restore review](consumer-restore-findings.md) covers partial and
failed restores that otherwise allowed stale transitive package inputs through
fresh export. It compares requested dependency semantics and restore completion,
preserving valid NuGet version resolution differences.
