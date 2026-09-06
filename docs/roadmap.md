# Roadmap from the current spike to a supported adapter

Planning baseline: 2026-09-06, branch checkpoint `6bd2525`. This roadmap starts
from the implemented exported-graph execution slice and continues through a
bounded, usable MSBuild-retaining Bazel adapter. It is a dependency plan, not a
promise of arbitrary MSBuild compatibility or a calendar schedule.

The [coverage matrix](scenario-coverage.md) defines P/G/F/C scenario IDs and K
capability slices. The [project selections](coverage-project-selections.md) pin
candidate source inspections. This document assigns that work to milestones;
contracts and findings remain the authority for exact behavior and measured
results. Later milestones are intentionally broader and must be split into
executable slices before implementation.

## Starting point and historical numbering

| Existing work | Evidence at this checkpoint | What remains |
| --- | --- | --- |
| Configured graph export | [Export findings](graph-export-findings.md): 12 tests passed on Linux x86-64. | Execution support does not automatically cover every exported configuration. |
| Generated graph execution | [Execution findings](graph-execution-findings.md): package-free Release/net10.0 diamond and root-project acceptance on macOS ARM64. | Linux execution evidence, generated-graph cache recovery, packages and broader configurations. |
| Explicit two-project adapter | [Replay](replay-findings.md), [Bazel](bazel-findings.md), [package](binary-package-findings.md) and [runtime](loader-runtime-findings.md) findings. | Transfer only measured behavior into the generated adapter; full host closure remains open. |
| Generated-graph cache tests | [Cache contract](graph-cache-contract.md): acceptance suite exists; probe is missing and tests are intentionally red. | Implementation and passing native execution evidence. |
| Serilog | [Pilot](real-project-pilot.md): pinned ordinary MSBuild baseline and API approval test on macOS. | Adapter build/test, output equivalence, cache recovery and comparative timings. |
| Broader portfolio | Pinned inspections and proposed coverage. | No portfolio-wide adapter support is established. |

Forward milestones use **R01–R17** to avoid reassigning numbers in historical
contracts and test diagnostics. Old milestone 1 is the export foundation; old
milestone 2 continues in R01; old milestone 3 spans R01/R02; old milestone 4
becomes R04; old milestones 5/6 become R13/R14. Historical findings retain their
original numbering and observations.

## Parallel execution plan

Use the [dependency graph](roadmap-graph.md) to schedule work packages within these
milestones. Its [machine-readable DAG](roadmap-graph.json) records acceptance
prerequisites and boundaries. The first parallel batch is Linux validation,
package-free cache implementation, replay/discovery controls and isolated
multi-language harness integration with existing Bazel rules. Shared runner/preparation edits still need one
owner; see the graph's coordination rules.

R04 is split into required generator/input contracts and Serilog application
acceptance. R05 depends on those contracts, not on waiting for the entire Serilog
pilot. Later broad milestone dependencies likewise refer to their selected
feature slices; the graph makes those joins explicit.

## Milestone map

All forward milestones are open. “Next” means ready for detailed implementation;
“planned” means prerequisites or contracts are still needed.

| Milestone | Outcome | Prerequisites | State |
| --- | --- | --- | --- |
| R01 | Reliable package-free generated graph and local cache | Existing execution slice | Next |
| R02 | Managed package closure in generated graph actions | R01 core execution/cache | Planned; existing cache contract includes these cases |
| R03 | Configured nodes, discovery and entry-point semantics | R01; R02 for package/SDK cases | Planned |
| R04 | First real-project adapter acceptance: Serilog | R02, selected R03 configuration support | Planned; ordinary baseline available |
| R05 | Generator combinations and project-reference roles | R04 input-contract slice; parallel with Serilog acceptance | Planned |
| R06 | Source-built tasks, package consumers and output lifecycle | R02–R05 slices actually used | Planned |
| R07 | Broader restore/runtime assets and ordinary publish modes | R02/R03; selected R06 task/output support | Planned |
| R08 | Native AOT publishing | R05 project generator, R07 publish/runtime contracts | Planned |
| R09 | Managed graph scale and useful performance | R02–R05 for real projects; synthetic measurements can start after R01 | Planned |
| R10 | Web/Razor, Blazor server and WebAssembly | R05/R06, selected R07 publish support | Planned |
| R11 | Desktop, Windows/Framework and managed languages | R03/R06/R07 slices and platform toolchains | Planned |
| R12 | Aspire mixed-language composition | R04 .NET foundation, existing-rule harness integration | Planned |
| R13 | Independent-worker remote cache | R01/R02 and explicit compatible-worker closure; R04 for Serilog extension | Planned; need not wait for R05–R12 |
| R14 | Actual remote execution | R13 identity/artifact validation plus declared execution closure | Planned; independent of portfolio breadth |
| R15 | Design-time and developer workflows | Stable local build/output contracts; selected desktop/generator support | Planned |
| R16 | dotnet/runtime managed slices, then native integration | R03/R06/R07; R09 measurement harness, R14 only for remote claims | Planned |
| R17 | Supported release and final adoption decision | Mandatory gates and named portfolio slices below | Planned |

Shared harness/input-contract changes land before dependent project experiments.
Independent baselines, source inventories and platform preparation may proceed
in parallel. A prerequisite means the required feature slice, not every optional
extension of an earlier milestone. A platform's result does not qualify another
platform, and remote support is qualified per workload/toolchain slice.

## R01 — Prove generated-graph local correctness and caching

Scope: the existing four-project diamond, package-free Release/net10.0, standard
outputs, native Linux x86-64 and macOS ARM64. Keep conservative dependency bundles,
normal MSBuild compilation and the local-only execution policy.

Deliverables:

1. Run the existing graph execution acceptance in Linux CI, preserving native
   sandboxing, declared input boundaries and dependency replay. Record failures
   as failures; do not weaken isolation to obtain platform coverage.
2. Implement `tools/probe_graph_cache.py` for the package-free cases in the
   [existing report contract](graph-cache-contract.md), with retained reports,
   execution logs and artifact digests. This is partial milestone-3 acceptance;
   the full existing cache suite remains red until R02 package cases pass.
3. Exercise cold, unchanged, App/Left/Shared/import edits and Right -> Left edge
   addition. Record expected/observed action sets and application output. Graph
   changes must go through export/preparation, not hand-edited Bazel files.
4. Prove disk-cache recovery with a fresh output base and relocation with the
   producer absent. Compare recovered bundle bytes/permissions and run App.
5. Add focused C13 handoff tests: stale preparation input, recoverable missing
   generated output, invalid materialized bundle, forced replay-semantic failure,
   and valid changed producer results. Capture which validation/execution boundary
   actually ran; a warm consumer hit does not exercise replay.
6. Add initial C14 discovery controls for a new globbed source and newly present
   optional import, plus concurrent builds of the supported configuration,
   interrupted publication and unsupported-global rejection.

Exit: package-free cases pass on both native lanes; each project compiles only
in its own action; cold/edited/recovered behavior matches ordinary MSBuild; stale
inputs and interrupted writes cannot publish usable partial results. Retain the
existing root-project and rejection regressions. Record the exact passing subset
without marking the full package-bearing cache contract complete.

Coverage: K01; C01–C09/C12–C15 within the baseline slice. No new TFM/RID support,
remote behavior or arbitrary custom target compatibility is implied.

## R02 — Integrate managed packages into generated graphs

Scope: move the explicit adapter's measured managed-package behavior into the
generated graph, beginning with a package used only by Left in the diamond.

Deliverables:

1. Define versioned per-node restore/package manifests and stage verified package
   payloads and installation metadata. Keep acquisition/restore in preparation;
   never resolve missing packages from a user's ambient cache during compilation.
2. Preserve compile versus runtime assets, direct/transitive dependency selection
   and the consumer's own restore closure. Dependency project bundles do not
   substitute for a consumer's package closure.
3. Implement the existing `packageCold`/`packageUpgrade` cases. A Left-only package
   upgrade rebuilds Left/App under the stated fixture contract, with observable
   runtime version changes; unaffected nodes retain their action identities.
4. Add a focused PrivateAssets control beyond the original cache suite: a library
   consumes a package privately, and an App references the library. Compare
   omitted/default metadata, `PrivateAssets=all` and `PrivateAssets=none` using
   baseline restore graphs and compiler/runtime inputs. Prove the library retains
   required local assets and the adapter does not blindly export its whole package
   closure to App. Define output-copy behavior from the ordinary SDK baseline,
   not from a blanket assumption that private means no file can reach App.
5. Complete missing/corrupt package, stale restore and stale graph controls with
   the specified diagnostics and no invalid replacement-plan publication.
6. Run the entire existing generated-graph cache suite, package-free controls
   included, through native Linux CI and macOS acceptance.

Exit: `python3 -m unittest discover -s tests/graph_cache -v` passes all existing
cases without skips, plus the new private-asset controls; the package-backed App
also executes after recovery and producer deletion. Keep binary-package explicit-adapter regressions. This closes
the original milestone-3 contract, not every later NuGet scenario.

Coverage: K02 initial slice, F04 selected package behavior, C03/C05/C08/C13/C14.

## R03 — Support configured dependencies and reliable discovery

Scope: the graph semantics needed before a faithful Serilog adapter baseline,
then separately qualified solution and custom-SDK entry points.

Deliverables and gates:

- **Required for R04:** preserve outer/inner framework selection without retargeting
  upstream projects. One path plus different globals yields different configured
  nodes; outputs cannot collide. Support the existing Serilog inner-build selection
  actually chosen by its baseline, or faithfully execute the required outer graph.
- Adapt upstream MSBuild `AdditionalProperties`/`GlobalPropertiesToRemove` graph
  shapes into executable fixtures. Two consumers select distinct dependency
  configurations; downstream nodes converge only when their effective globals do.
  Incompatible selection/replay properties fail explicitly.
- Re-evaluate when glob membership, optional imports, conditional references or
  edge metadata change. Compare old/new manifests and actual Bazel dependencies.
- **Entry-point extension (F13):** solution configuration mappings, exclusions and
  solution-only edges; compare traversal/solution only for equivalent semantics.
  Qualify .sln, .slnx and filters separately under the selected SDK.
- **SDK extension (F14):** pinned Traversal/package SDK plus a repository-local SDK
  fixture. Declare resolver/import inputs; version/import changes invalidate
  preparation and missing SDKs cannot silently fall back to host state.

Exit: each claimed configuration/entry-point slice has baseline, action-set,
relocation and rejection evidence. R04 can start after the required configured-node
slice; it need not wait for every solution format or resolver extension.

Coverage: K03, C06/C07/C13/C14/C15, F13/F14; upstream fixture pins are in the
[selection record](coverage-project-selections.md).

## R04 — Run Serilog through the adapter

Scope: P01's pinned approval-test project and Serilog dependency. Retain signing,
PolySharp, shared imports, resources and selected framework semantics.

Deliverables:

1. Inventory evaluated inputs against the existing pilot findings. Declare signing
   key, generator/analyzer assemblies and dependencies, compiler options, resources,
   test data and runtime outputs. Add small failing fixtures before expanding each
   input/output contract; no broad analyzer compatibility shortcut.
2. Run an unchanged upstream ordinary MSBuild baseline on each claimed platform,
   then the same selected configuration through the adapter. Execute the API
   approval test and a logging-behavior oracle without hidden build/restore.
3. Perturb library/test source, signing key, shared version/import input and the
   selected generator/package version independently; require expected invalidation
   and explicit missing-input failures.
4. Recover into an independent output base and relocated checkout with no producer
   access; run tests against recovered artifacts. Compare named consumer outputs,
   reference/runtime identities and signing properties under a declared oracle.
5. Measure repeated fresh, unchanged, edited and recovered runs against MSBuild,
   reporting setup/restore and cache/host state separately. Do not claim speedup
   from the existing single baseline timing samples.

Exit: P01 Build/Test passes on Linux x86-64 and macOS ARM64 for the declared slice,
with its contracts, test IDs, logs and exclusions linked from the coverage matrix.
A successful ordinary baseline is not completion. Windows/Framework and publish
remain separately qualified work.

Coverage: selected K02–K05, G05/G07–G09/G11, F07/F09/F10 and applicable local C checks.

## R05 — Qualify generator combinations and reference roles

Start with small API/delivery fixtures, then P02 Spectre.Console, P16
CommunityToolkit.Mvvm and P14 Dapper.AOT. Begin after R04's required input-contract
slice passes; R04's Serilog acceptance and the R05 generator/interceptor tracks
may then proceed independently.

- Cover classic/incremental APIs independently from ordinary/interceptor output;
  include SDK-, package- and project-delivered assemblies where selected. Add
  diagnostic-only analyzer severity/suppression/warnings-as-errors controls.
- In P16, preserve ordinary, analyzer and packaging/build-order references; verify
  the chosen multi-framework graph and conditional package mutations. On Windows,
  use the selected net472/net8 comparison; qualify a Linux net8 slice independently.
- Use P02 for additional JSON inputs/shared generator projects. Changes to
  AdditionalFiles/configuration/dependencies must invalidate the right consumers;
  removed inputs cannot leave stale generated code.
- Use P14 to prove actual interception, including file rename, inserted lines,
  changed/removed calls and relocated cache recovery. Pin compiler feature settings
  and generator location encoding; source generation alone is not Native AOT.

Exit: chosen combinations have cold/recovered behavioral and diagnostic evidence,
with correct reference/runtime roles and no undeclared generator process state.
All G01–G11 have an explicit passing slice or an explicitly deferred combination;
no claim of a full cross-product is required.

## R06 — Build tasks, consume packages and define output lifecycle

Use P05's source-task and package-consumer slices, then P17 Nerdbank.GitVersioning
and P16's analyzer-package extension.

Establish task producer ordering even when UsingTask is not a ProjectReference;
stage task/dependency/task-host closure and execute consumers without producer
paths. Preserve Avalonia's required package creation/patching, restore local
packages into a fresh consumer, and verify compiled XAML. P16 separately tests
packed analyzer selection; P17 adds controlled Git/version inputs and executable
build-order outputs. Broader native dependencies are gated by the selected R07
slice rather than being assumed available.

Define F15 Clean/Rebuild ownership before exposing commands: deletions cannot be
skipped by cache hits; cache purge is separate; force-compilation versus recovered
Rebuild semantics must be explicit. Verify configuration preservation, stale
output removal, interrupted operations and subsequent recovery.

Exit: selected F05/F09/F10/F15 operations have independent baseline/adapter evidence;
Build, Pack, consumer restore, Test and state-changing commands remain distinct.

## R07 — Expand restore, runtime assets and ordinary publishing

Add F04 central versions/locks/conditional references/conflicts and buildTransitive
as separately tested restore slices. Expand R02's PrivateAssets baseline to
selected compile/runtime/build/buildTransitive/analyzer categories and their
interaction with IncludeAssets/ExcludeAssets. Compare the declaring project and
transitive consumers separately; mutate metadata without changing package bytes
to verify restore/plan/action invalidation. Pack a library and inspect its .nuspec
dependency metadata, then restore an independent package consumer (F05/R06). Do
not equate PrivateAssets with removing the declaring project's own inputs.

Use the [NuGet asset metadata contract](https://learn.microsoft.com/en-us/nuget/consume-packages/package-references-in-project-files#controlling-dependency-assets)
and pinned ordinary restore/build/pack results as the semantic baseline. Extend to F03 RID/native
assets, F07 satellite resources/content/plugins and the named F06 publish modes:
framework-dependent, self-contained, single-file, trimmed and ReadyToRun.

For each slice, define selection and full consumer/tool/runtime inputs, then
execute recovered output on the named target. Qualify native and cross-target
pairs separately; build-host success cannot stand in for target execution.
Publishing has its own target/global-property identity and output contract.

Exit: supported restore/publish/runtime modes and rejected combinations are listed
with per-platform evidence. Full arbitrary NuGet or host closure is not inferred.

## R08 — Publish and execute Native AOT

Use P08 ConsoleAppFramework's native tests. Declare source-generator dependencies,
managed publish closure, AOT compiler/linker/runtime packs and execution/target
platforms. Begin with native Linux x86-64 publishing linux-x64.

Exit: fresh and recovered published test binaries execute without a .NET runtime;
compiler/linker/runtime-pack changes invalidate correctly and missing tools fail
without host fallback. Cross-compilation is a later named slice. WebAssembly AOT
belongs to R10, not this executable-publish claim.

## R09 — Establish graph scale and useful performance

Run C16 synthetic 10/100/1,000-node chain and fan-in/fan-out graphs, then P03 EF
Core and P06 Azure SDK subtrees. Start synthetic measurement after R01; real
project acceptance waits only for its actual feature prerequisites.

Follow the coverage document's independent cache-state and MSBuild comparison
protocol. Predeclare each system's expected work sets; compare observable results,
not identical compilation counts. Record preparation/analysis/execution costs,
process-tree memory and graph sizes. Set numeric qualification budgets after
baseline calibration but before qualification runs.

Exit: correctness at the claimed scales, reproducible performance reports and a
clear statement of where the adapter helps or adds overhead. Optimize reference-
assembly or metadata inputs only with tests proving omitted changes irrelevant.

## R10 — Qualify web, Razor and Blazor applications

P04 Orchard supplies modular hosting/themes and frontend assets; P09 MudBlazor
supplies component/static-asset and WebAssembly pipelines; P18 supplies server
interactivity. Pin frontend tools and browser/runtime inputs. Add WebAssembly AOT
only with its workload/toolchain closure.

Exit: recovered published apps serve intended assets/modules and pass browser
oracles. Server-side tests prove a live circuit/state change, not just HTML;
WebAssembly tests execute in the browser. Each render/publish mode has separate
Build/Publish/Launch/Test evidence.

## R11 — Qualify desktop, Framework and managed-language lanes

Use P05 headless/XAML then native rendering; P10/P11 WPF and P12/P13 WinForms
separate modern .NET from Framework. Use F01's VB app/library and F# candidate,
then authored mixed-language edges. F02 adds classic non-SDK C#/VB projects and
packages.config restore/consumer integration.

Exit: declared Windows/Linux/macOS lanes pass their selected compile, resource,
reference and recovered-runtime/UI checks. SDK-style Framework does not qualify
classic projects, and headless layout does not qualify native rendering. Platform
SDKs, reference assemblies and native libraries are explicit prerequisites.

## R12 — Compose the Aspire polyglot application

Integrate our .NET adapter with existing Bazel Python/JavaScript/TypeScript rules
in a shared multi-language harness, then exercise P07 Aspire composition. Reuse
[rules_python](https://github.com/bazel-contrib/rules_python),
[rules_js](https://github.com/aspect-build/rules_js) and
[rules_ts](https://github.com/aspect-build/rules_ts) where appropriate. Select
versions compatible with the pinned Bazel toolchain; rule/tool pins are still
preparation work, not established compatibility evidence.

The work is integration: a shared Bazel workspace/module configuration, target
wiring, runfiles/runtime artifact handoff, common test orchestration and comparable
execution/cache evidence. Existing rules own Python/Node toolchains, package
resolution and language actions. Our implementation owns the MSBuild adapter and
the glue needed to compose its outputs with those rules. New Python/TypeScript
build-rule implementations are outside this milestone.

Start with a small .NET + Python + TypeScript harness independently of Aspire.
Then connect recovered targets to P07 service startup, readiness and its message
flow. Keep build/generated-contract edges distinct from runtime relationships;
MSBuild replay applies only to .NET. Use the upstream rules' declared dependency
and toolchain mechanisms and pin their inputs for reproducibility.

Exit: one harness builds/tests all three languages; language-local edits reuse
unrelated outputs; shared-contract changes invalidate the intended consumers;
fresh-output/cache-recovery runs preserve runfiles and runtime dependencies.
Aspire launches the recovered artifacts without hidden build/restore and passes
the selected message-flow oracle. Services/tests start fresh; their lifecycle is
not a cacheable compiler action.

## R13 — Prove independent-worker remote caching

Use the selected bazel-remote deployment with the diamond first, then P01. Start
when R01/R02 local correctness and a compatible-worker input/toolchain identity
contract are ready; do not wait for the whole portfolio.

Exit: worker B, with an independent checkout and empty local build caches, recovers
worker A's results from the remote service and executes App/tests. Retain client/
server hit evidence, producer-absence checks and incompatible-environment controls.
Resolve undeclared inputs relevant to the claimed worker equivalence; provisioned
host assumptions must be explicit. This proves only named compatible-worker
slices, not cross-OS sharing or remote execution.

## R14 — Execute MSBuild actions remotely

Use the selected Buildbarn deployment. Declare/provision the full execution
closure for the initial Linux diamond; then add P01 and later qualified workloads.
Pin service/worker images, SDK/runtime/native inputs and operation identities.

Exit: identities absent from enabled caches execute on remote workers, local
fallback is disabled, outputs match the baseline and missing tool/runtime inputs
fail explicitly. Workers cannot depend on producer state or compilation-time
acquisition. Maintain separate remote-hit and remote-execution tests.

## R15 — Support design-time and developer workflows

Use F11 project-system target tests, followed by a declared Windows/Visual Studio
integration lane. Separate design-time globals/target results from Build. Verify
references, generated-source visibility, IntelliSense and debugging of recovered
artifacts in named slices. Watch/hot reload require their own lifecycle contract.

Exit: document supported IDE/CLI workflows with executable evidence and explicit
unsupported operations. A command-line build or mocked target test alone cannot
qualify IDE behavior. R15 core design-time support precedes a developer-workflow
claim; advanced IDE extensions need not block a CLI-only release.

## R16 — Grow into dotnet/runtime

P15 begins with a pinned managed library subtree and explicit bootstrap/global
property contracts. Expand to required managed tooling, native shims and eventually
larger runtime builds only after the smaller slices pass. Reuse R09 measurements
and selected native/publish support; remote claims additionally require R14.

Exit: independently reproducible managed and then native slices, with documented
adoption cost, bootstrap boundaries, cache correctness and target execution.
Whole-repository compatibility is a separate expansion, not implied by a library
pilot. MAUI/mobile F12, C++/CLI and additional architectures remain optional later
tracks with explicit workload/signing/device contracts when brought into scope.

## R17 — Deliver the supported adapter and adoption conclusion

The endpoint is a documented support envelope, not a universal .NET build engine.
Keep MSBuild/SDK/NuGet semantics inside declared, versioned action contracts.

Mandatory release gates:

- R01–R04 pass their named baseline lanes; the adapter has a repeatable supported
  prepare/export/build entry point, actionable rejection diagnostics and no hidden
  dependency recompilation or ambient restore fallback.
- Required R03 entry-point/SDK and R06 lifecycle contracts are documented; each
  exposed operation either has evidence or is explicitly rejected. Supported
  toolchain/package/configuration combinations are versioned and regression-tested.
- Each portfolio slice P01–P18 and fixture/generator category has an honest final
  disposition: measured support with links, a reproducible known limitation, or
  explicit deferral with rationale. Deferred rows are not counted as coverage.
- R09 supplies reproducible cost/benefit measurements. R13/R14 pass for at least
  the initial declared workload before the full local-and-remote roadmap is
  considered complete; a local-only release may precede that endpoint.
- Installation/tool acquisition, CI reproduction, artifact schemas, cache identity
  compatibility and upgrade invalidation are documented and exercised. Platform-
  specific tests and negative controls remain available to future maintainers.

Produce a final adoption report explaining which workloads benefit, what project
integration requires, unresolved limitations and whether further investment is
justified. A demonstrated blocker may change the recommended scope; it is not a
passing implementation milestone. Optional mobile, advanced IDE, full-runtime
and cross-platform reuse claims remain outside the release until separately
qualified. No fixed completion date or blanket compatibility percentage is implied.

## Evidence rules for every milestone

Write the contract and executable failing acceptance before implementation. Keep
experiments independently runnable and restore/tool acquisition outside build
measurement. Retain exact pins, commands, worker/configuration identities, test
IDs, expected/observed work sets, artifact/runtime oracles, logs and limitations.
Use native sandbox execution and Linux CI where claimed; do not label a missing
tool/network failure as a pass or silently skip a required case.

Update the [coverage matrix](scenario-coverage.md) per measured slice and link its
findings here. Historical evidence remains scoped to its original platform and
contract. Consult the [risk register](edge-cases-and-risks.md) when refining tests;
this roadmap does not override narrower implementation contracts.
