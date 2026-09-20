# MSBuild / Bazel implementation plan

[Action-local validation and direct caching](action-local-cache-validation.md)
passes a real small-graph producer-deleted recovery and failed-publication
control. Its loopback measurements do not justify changing the gated default.

The [evaluated API/runtime boundary](native-api-runtime.md) follows the changed
HTTP-cache baseline, separating ordinary project compilation reuse from current
runtime composition while retaining SDK/package metadata in dependency keys.

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

The [canonical-runtime, recovery and no-op follow-up](runtime-recovery-performance.md)
reduces Orchard CSS/Razor edits to 12.889 / 12.028 seconds and no-op median to
2.820 seconds. Composition emits one application tree plus sealed metadata;
fresh recovery downloads 676.8 MB instead of 2.02 GB and completes in 29.353
seconds with no compilation and 3,457 identical application files. Preserving
unchanged generated inputs cuts the measured no-op Bazel phase to 0.259 seconds.
Download concurrency is configurable, with an unchanged default of eight:
32 connections help simulated latency but show no full-recovery benefit on this
loopback run. Native input invalidation and the Serilog .NET 10 test/recovery/failure
controls pass. Initial source capture, exit validation and generation now dominate
no-op overhead; fresh-worker analysis and setup remain larger than network transfer
in the measured local profile.


The [cache-publication and runtime-output follow-up](cache-publication-performance.md)
reduces CSS/Razor edits to 21.854 / 20.226 seconds, from 53.021 / 49.562 seconds.
Publication checks current remote CAS presence and uploads only missing blobs with
bounded concurrency, preserving the content-before-action barrier. Each edit
uploads about 2.39 MB instead of 648.7 MB. Smaller Bazel runtime projections reduce
composition input files by 70.6%; paired direct composition is 12.3% faster with
10,383 identical output files and modes. Producer-deleted recovery passes in
34.551 seconds with 3,457 identical application files, no compilation and no
extracted package downloads; no-op median is 6.698 seconds. Complete entry-output
composition and local staging remain the next measured edit costs.


The [resource-body optimization](resource-body-performance.md) moves evaluated
resource contents into per-project Bazel binding actions. On the 202-project
Orchard graph, CSS edits fall from 338.668 s to 53.021 s; Razor edits take 49.562 s.
Both execute one binding and one compilation, with zero restore/discovery.
Namespace and import changes still invalidate discovery. Producer-deleted remote
recovery takes 37.809 s with no compilation, 3,457 identical application files
and no extracted package-file downloads; median no-op is 6.754 s. Runtime
composition and cache publication measurements provide the baseline for the
follow-up above.
The [preceding discovery/binding work](discovery-binding-performance.md) retains
the cold-discovery profiling and comparison baseline.


The [local MVP release](local-mvp-release.md), **v0.1.0-mvp.1**, provides the
pinned native macOS ARM64 Build/Test source release. Its
[release sign-off](local-mvp-signoff.md) records a rerun on merged main,
complete Build/Test measurements, compatibility policy, retained limitations and
reproducible evidence. Broader compile/runtime boundary and scale work remain
open; the next performance milestone is #34.

The [incremental preparation experiment](incremental-preparation-findings.md)
removes repeated materialization, adds explicit protected-store session reuse,
and qualifies content-only C# graph refresh. It measures each change separately
and retains full mutable-input validation after a missed-event counterexample.
These focused results do not replace the frozen MVP release qualification.

The [local MVP candidate contract](local-mvp-contract.md) maps GitHub #63,
#5, #6, #7, #64 and #65 to a single native macOS ARM64/Nix Build/Test release
slice. The initial [calibration](local-mvp-calibration-findings.md) found a
preparation latency regression. The [performance qualification](local-mvp-performance-findings.md)
now passes the unchanged budget: median reuse is 1.544s versus 2.271s fresh for
the small fixture and 1.866s versus 2.184s for Serilog. Full hashing and lease
validation remain enforced; the adapter still has end-to-end overhead on the
small Build/Test workload. The [clean-candidate qualification](local-mvp-release-qualification.md)
passes 99 correctness cases, 20 paired preparation samples and 40 Build/Test
samples, with exact code/evidence applicability recorded. The original
[85-case matrix](local-mvp-correctness-findings.md) and
[macOS path guard](local-mvp-path-findings.md) remain part of the contract.
The subsequent [#65 release](local-mvp-signoff.md) records delivery and fresh
qualification; broader platform, package and scale work stays open.

The first [MSBuild time-input diagnostic slice](msbuild-time-findings.md) reports
potential clock and file-timestamp reads in project/import XML, excluding application
source. An explicit build-ID probe passes five ordinary MSBuild cases; this does
not authorize preparation reuse or establish general timestamp eligibility.
The [evaluated-import extension](evaluated-time-findings.md) adds verified graph
XML scanning and configured ownership; its real SDK optional-import control
demonstrates why a verified old inventory cannot authorize reuse.
The [RUL-5 observation design](preparation-observation-design.md) now prioritizes
MSBuild filesystem hooks to record and revalidate content reads, absent-file
probes and directory enumeration, with explicit invocation inputs and enforced
coverage before reuse.

The [discovery contract](discovery-contract.md) adds enforced eligibility for the
selected Release/net10.0 GraphExport operation, including its SDK discovery
targets and the pinned Serilog library. It stages a private input view, hashes
complete declared trees to cover the measured hook gaps, verifies qualified
SDK/package imports, rejects unsupported executable XML, and runs discovery in
a native macOS sandbox. Candidate validation rechecks content and external
absences without running discovery. The [RUL-6 preparation cache](preparation-reuse-findings.md) adds opt-in
prepared-artifact reuse, integrity verification, atomic publication/recovery and
consumption under a retained lease. Validation-cost measurement remains RUL-7.

RUL-6 native macOS qualification (2026-09-09) passes all 17 small-graph
reuse/publication cases, including two-process serialization and producer-free
recovered execution. The pinned Serilog library also passes cold/recovered
preparation, a fresh native build and an executable consumer after producer
deletion. Forty preparation unit tests and 31 focused graph
materialization/selection/closure regressions pass; repository and .NET style
checks pass. See [commands, evidence and limitations](preparation-reuse-findings.md).
No Linux or CI workflow was dispatched.
The 2026-09-14 readiness correction distinguishes an already-invalid external
absence from a mutation during accepted consumption. All 43 preparation tests
pass, including three new lease/fallback regressions; see the linked findings.

Final RUL-5 qualification (2026-09-08, native macOS ARM64, Nix SDK 10.0.400):
31 identity/contract unit tests and 22 MSBuild diagnostic tests pass. The final
small-graph matrix passes all 27 cases at
`/private/tmp/rul5-contract-final-2/report.json`; the unchanged pinned Serilog
library passes all 15 cases at
`/private/tmp/rul5-serilog-contract-final/report.json`. `bash scripts/check.sh`
and `bash scripts/check-dotnet.sh` pass, including all five code-style enforcement
tests; `git diff --check` passes. The first repository check was blocked by the
agent sandbox's Bazel output-directory restriction; the native rerun passed.
An intermediate test expected an MSBuild error-code prefix on an exception
message; the final negative control instead asserts the actual missing-import
diagnostic and independently verifies that the denied external file exists.
No CI workflow was dispatched. These results complete the selected RUL-5
discovery identity/eligibility gate, not R09 production reuse or performance.

Repository-owned .NET tooling and unit tests now have [build-enforced code style
and warning policies](code-style-findings.md), separate from fixture build semantics.

The added R01 [Starlark baseline](starlark-core-findings.md) now passes on native
macOS and local Linux ARM64: pinned formatting/lint, rule analysis, prepared-workspace and repository
controls, with cache/discovery/forced-replay regressions retained. The additional
`starlark_packages`, `starlark_configured` and `starlark_tests` gates now pass
[native macOS qualification](r02-r04-validation-findings.md), including generated
workspaces, real generator-version changes and cold/recovered reference consumers.
The [shared R05 versioning fixture](shared-versioning-findings.md) qualifies
Nerdbank 3.9.50 with explicitly supplied `NBGV_CacheMode=None`, SourceLink
8.0.0/10.0.300 and DotNet.ReproducibleBuilds 2.0.2 on macOS ARM64. Both 13-case
matrices cover version/SourceLink parity, input invalidation, relocated disk-cache
recovery and rejection controls. [Default auxiliary-project caching](default-versioning-findings.md) is also
qualified (RUL-94). [R05 qualification](r05-qualification.md) now includes the
selected CommunityToolkit and Dapper.AOT mutation/recovery gates and an explicit
G01–G11 disposition.

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

## Adapter tool build inputs

GraphExport and ReplayPlugin accept explicit tool-framework and reference-engine
inputs while preserving the net10.0/current-engine defaults. The [tool-input
findings](tool-input-findings.md) record native compilation/loading, selected
18.10.1 replay with SDK-10 application semantics, and actual cross-engine payload
rejection. Full new-engine graph/cache qualification remains separate; a default
diamond MSB4252 failure also reproduces on the unchanged baseline.

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

The support target is **deterministic CI builds**, with explicit build-time inputs
and a qualified file timestamp policy. The [support contract](deterministic-ci-contract.md)
defines eligibility and acceptance gates; it does not enable R09 reuse or expand
measured compatibility. The [portfolio time audit](project-time-audit.md) covers
all P01–P18 entries and supplemental sources, separating clock-dependent build
outputs, file metadata and runtime/test behavior. Its source observations are
planning evidence; selected configurations still need execution qualification.

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

### R05 CommunityToolkit configured graph acceptance

The [CommunityToolkit findings](toolkit-findings.md) record 11 native macOS
ARM64 actions and 69 passing upstream tests at the pinned revision, including
same-project net8.0/netstandard2.0 identities, ordinary/analyzer/build-order
references and default Nerdbank. All seven mutation/recovery cases now pass,
including exact rebuild sets, 11 relocated disk-cache hits and fresh recovered
consumer compilation. The selected framework native regression also passes
after retaining unique transitive selections.

### R05 package-delivered interception

The [Dapper.AOT findings](interceptor-findings.md) record the actual interception
oracle, 11 mutation/recovery cases, pinned path/line/column encoding and explicit
compiler feature failures. Language-independent analyzer package payloads retain
archive and per-file integrity guards. Acquisition, native Build/Test and Native
AOT/Pack qualification are explicitly separate.

## Rule-selected build SDK

[Explicit build SDK inputs](rule-toolchain-findings.md) connect `sdk_version` on
both project rules with preparation's `sdk_root`/`sdk_version`, exact engine
execution, compiler host selection and replay SDK identity. Project target
framework declarations remain independent. The findings bound native qualification
and describe the complete SDK payload requirement.

## Measured MSBuild parity follow-up

See [MSBuild parity findings](msbuild-parity-findings.md) for preparation reuse,
opt-in package-free API/runtime separation, flattened runtime composition, and
complete-workflow measurements. Cold-build parity remains open.

The [raw MSBuild batch experiment](msbuild-batch-findings.md) measures one native
sandboxed whole-graph action without upfront graph export. It cuts cold overhead
but rebuilds all 100 projects on a source edit; fixed intermediate groups remain
future work.

The [MSBuild plugin-cache investigation](msbuild-plugin-cache-findings.md) pins
and tests Microsoft's published cache package. ARM64 assembly loading and the
missing file-access-reporting feature block its use on the current SDK. SDK-native
project-cache callbacks work; an explicit-input cache remains a separate prototype.

The [native explicit-input cache prototype](msbuild-native-cache-findings.md)
retains one MSBuild graph scheduler with per-project API-based cache decisions and
current runtime composition. Fresh-workspace recovery and edit/corruption/failure
checks pass for owned package-free fixtures; general-project and sandbox support
remain outside this experiment.

The [isolated-consumer HTTP comparison](remote-cache-comparison.md) tests actual
remote transfers for Bazel-owned project actions and native MSBuild project
bundles, plus whole-graph outer-cache behavior. It uses loopback storage and
fresh consumer build state; worker integration and cross-host qualification
remain separate gates.

The [portable sandboxed native cache](sandboxed-native-cache-findings.md) uses
explicit project-cache seed inputs and post-success publication around one native
Bazel graph action. It removes controller-location identities, tests independent
restore/controller roots, and measures fresh-consumer versus retained-server
costs. The macOS read/temporary-directory limitations are recorded explicitly.

The [native-cache overhead follow-up](native-cache-overhead-findings.md) measures
publication reuse independently from avoiding unused language-rule autoloads in
the generated workspace. It retains Bazel profiles and explicit request counts;
repeated downloads and the remaining cold-action cost are still open.

The [startup overlap experiment](native-cache-startup-findings.md) overlaps the
required Bazel platform query with full SDK fingerprinting and seed preparation.
It includes startup costs in wall time and preserves serial/JVM-only controls;
public repository acquisition remains a source of cold-run variation.

The [merge review and Serilog boundary check](native-cache-review.md) records
malformed-cache fixes, local regression validation, passing existing-adapter
package/test acceptance and the still-rejected native-cache real-project boundary.
It defines the next package/generator qualification slice without broadening the
prototype's eligibility.

The [native-cache Serilog qualification](native-cache-serilog.md) adds an opt-in
evaluated-graph/package-manifest input path, complete SDK runtime bundles and
conservative dependency implementation keys. Input preparation, execution and
upstream acceptance are separate commits. The pinned library and approval graph
have native macOS sandbox, HTTP recovery, mutation, corruption and actual-test
evidence, with the code-coverage and cross-host limitations recorded explicitly.

The [native Build/Test workflow](native-workflow.md) adds an explicit native-cache
command and a Bazel test rule consuming sealed outputs and declared test data.
Leased native-plan reuse and [complete-workflow measurements](native-workflow-performance.md)
are separate follow-up commits. The timing report distinguishes correctness
acceptance from the explicit raw-MSBuild performance target.

The [native workflow overhead follow-up](native-workflow-optimization.md) records
separately measured generated-workspace retention, verified package reuse on C#
edits, invocation identity sharing with final checks, and larger-graph comparisons.

The [remote preparation workflow](remote-preparation.md) adds explicit immutable
HTTP snapshots for discovery/native-plan reuse on fresh consumers. It retains
leased validation, guarded source refresh and project reference-assembly
invalidation, with producer-deleted correctness and end-to-end measurements.

[NuGet global-cache reuse](nuget-cache-reuse.md) stages the restored package
closure into private inputs and reconstructs split remote preparation package
objects from verified local bytes, preserving the build input and publication checks.

[Split preparation objects and network measurements](preparation-components.md)
extend reuse to source groups, graph metadata, and SDK evidence. The HTTP probe
shares bandwidth across concurrent transfers and measures unchanged, body-edit,
and package-upgrade consumers under explicit latency and bandwidth limits.

## Production Python removal

See [the migration record](python-removal.md) for staged removal of Python from
production preparation, orchestration and bootstrap while retaining test harnesses.

The .NET production controller now owns fresh preparation, sealed discovery, local
reuse, guarded source refresh, HTTP snapshots, NuGet cache staging and native
Build/Test. Shell/.NET bootstrap and validation need no Python. The migration
record includes 13 producer-deleted/negative consumer cases and the remaining
platform qualification limits. Python probes and reference implementations remain
test-only; use `scripts/build.sh` and `scripts/prepare.sh` in production.

## Independent workers

[The compatible-worker contract](compatible-workers.md) binds SDK/task/runtime,
Bazel and system-tool bytes plus conservative OS/hardware equivalence independently
of output TFM/RID. Independent mode restricts remote consumption/publication to
qualified discovery. Separate-host acceptance and new .NET timing measurements
follow this identity step.

[The pinned real-service harness](independent-remote-cache.md) now provides
producer/consumer handoffs, same-machine rejection, transport accounting and
passing same-host recovery/failed-test controls. Actual second-host acceptance
still needs a compatible worker. [The new .NET measurements](dotnet-worker-performance.md)
record 24 passing correctness comparisons and a missed end-to-end performance
target; identity/lease verification and the Bazel phase dominate small-graph
loopback recovery.

[Cache-hit overhead](cache-hit-overhead.md) removes duplicate final integrity
scans without retaining validation across invocations, separates optional Bazel
installation reuse from consumer build state, and analyzes Bazel JSON traces to
distinguish startup, registry downloads, analysis and cache-hit actions.

[Pinned Bazel repository-cache reuse](bazel-repository-cache.md) stages a reviewed
native module lockfile in error mode and exposes a separate verified download
cache. Fresh native recovery, network-denied platform resolution, missing/corrupt
objects and incomplete-lock rejection are covered by focused controls. The
measurement protocol separates lockfile-only and shared-download effects while
retaining fresh project build state and exact output/execution checks.

[Streaming integrity checks](integrity-streaming.md) replace full-file buffering
on hash-only paths with a bounded pooled buffer. Opt-in profiling separates I/O,
hashing, allocations and manifest comparison; all 19 SDK-tree digests remain
identical. Mutation and special-file controls pass, and repeated unprofiled
unchanged/body-edit comparisons record the end-to-end improvement while retaining
full validation and fresh consumer build state.

[Bazel analysis and materialization](bazel-materialization.md) profiles startup,
SDK package loading, sandbox/runfiles setup and native runner/test phases. It
retains the existing shared complete SDK declarations after checking actual
inputs, and removes redundant runtime export copies with sealed-output parity
and repeated fresh-consumer measurements.

[Whole-action HTTP cache integration](remote-action-cache.md) adds read-only
Bazel action-cache consumption and opt-in publication gated on successful tests,
live-input validation and output validation. Fresh-workspace hits preserve forced
tests; changed actions fall back to per-project reuse. Seeds remain declared
inputs, so the qualified experiment explicitly primes the seeded action variant.

[Persistent native cache hosting](native-cache-service.md) now provides a pinned
macOS user launch agent with loopback access and an SSH-tunnel runbook. Local
restart and disk-persistence acceptance passed; independent-worker validation
still requires a second compatible Mac.

[Linux ARM64 cache workers](linux-cache-workers.md) adds the selected Ubuntu
workflow lane, namespace-isolated discovery, native Linux Bazel sandboxing and
a producer-deletion/consumer-recovery harness using Apple containers. This is
separate from physical-machine and cross-platform qualification.

[Within-scan alias digest reuse](integrity-alias-reuse.md) removes repeated LLVM/
ICU reads while retaining independent final validation. Exact manifest parity,
mutation guards and repeated complete-workflow comparisons pass; remote-hit
medians improved by 2.8–5.3% in the recorded run.

[Current runtime seeds and automatic priming](canonical-seeds.md) remove the
qualified build-history variation and automatically populate the full-seed
Bazel action on uploading producers. Both seed histories recover one action;
failed-primer, failed-test and live-input mutation controls pass. The final
combined Linux two-VM qualification also passes. Partial/full seed variants
remain distinct declared actions, and physical-machine/WAN validation remains open.

[Focused integrity profiling](integrity-workflow-profile.md) attributes approximately 1.22 seconds per Serilog invocation to repeated runtime scans, dominated by the SDK and LLVM. Six off/on pairs plus fresh/edit diagnostics preserve worker identities, scan counts and outputs. No scan-elision optimization is implemented.

[Protected native sessions](protected-toolchain-session.md) add opt-in process-local reuse of audited system Nix roots. Candidate `4d025a0` reduces warm-worker hit medians from 2.055/4.944 to 0.680/3.338 seconds for diamond/Serilog. Mutable-input, controller/SDK identity and rejected-publication controls pass. The rules_go comparison points toward Bazel-owned discovery as the next architectural boundary; current reuse explicitly trusts privileged Nix administration/storage until session restart.

[Bazel-owned preparation](bazel-owned-preparation.md) adds a cacheable preparation
action whose declared tree feeds build and test, with the wrapped Nix SDK/runtime
closure as Bazel inputs. It retains strict native discovery sandboxing, automatic
seed priming and gated publication. This opt-in macOS slice keeps restore explicit;
the [direct-input follow-up](bazel-direct-inputs.md) now reuses discovery for source
body edits, acquires package/tool inputs through repositories, and exposes opt-in
per-project actions with stable API/runtime contracts. The performance target is
large-graph cache hits and edits; small-graph overhead is an accepted tradeoff.
Linux/default-workflow migration remains separate.

Large-graph qualification now compares 16/64-project fan graphs. Removing repeated
all-project runtime composition cuts its 64-project action from 6.775 to 0.272 s;
40 scale cases and final Serilog qualification pass. Per-project warm edits improve
about 30% at 64 projects, while fresh-worker cache hits/edits remain slower than
the whole-graph lane. Removing bootstrap/analysis/cache overhead is the next
performance target; small-graph parity is not the gate. See the
[measured tradeoffs and evidence](bazel-direct-inputs.md#large-graph-measurement-and-decision).

The [single-pass follow-up](bazel-single-pass.md) introduces a portable MSBuild-generated
project layout and a cacheable whole-layout validation action. A declared layout
lets fresh workers use one Bazel invocation; stale declarations fail before publication.

The direct-checkout slice exposes source files through a Bazel repository and
normalizes restore metadata in a declared action. It removes controller source
copying while retaining independent final input verification and publication gating.

Single-entry project actions now use the public MSBuild build API and replay-only
private dependency projects, retaining real SDK target outputs and strict input
validation. Qualification passes; 64-project total compile time improved 6.2%,
while wall-time gains were modest. See the single-pass findings for scope.

The optional locked-restore lane now removes the external worker restore prerequisite.
Bazel consumes NuGet-generated lock files, acquires verified package archives and
runs a strictly sandboxed, offline MSBuild Restore action. Fresh workers and body
edits recover restore remotely. All 22 qualification cases and seven raw oracles
pass, including stale-lock/source-read guards and zero failed-run publication.

## Orchard Core large-application support

The [Orchard pilot](orchard-pilot.md) pins the full CMS host as the next real
workload: 202 projects, mixed application/generator frameworks, Razor/module
assets and central transitive NuGet pinning. The raw baseline succeeds; adapter
qualification is in progress. Follow its acceptance gates through independent
remote-cache recovery and changed-input controls before claiming support.

[Project-owned structural inputs](project-input-scoping.md) narrows generated
compile declarations using validated MSBuild ownership. Native four-project
mutation controls pass. The Orchard stylesheet edit now compiles four projects
instead of 202 and takes 651.774 seconds instead of 1,108.482; runtime markers
and unchanged-output checks pass. Whole-graph discovery remains expensive.

[NuGet package actions](nuget-package-actions.md) now integrates cacheable package
directories into the opt-in owned locked-restore workflow. Two-package native
producer, producer-deleted fresh remote recovery, byte parity and source edit
checks pass. Full Orchard qualification and project-specific package sets follow.

[Project-specific package inputs](project-package-inputs.md) narrows compile
actions to validated package closures. Native fresh-recovery/source-edit evidence
shows the selected package materialized while an unrelated sibling package stays
remote. The full Orchard benchmark is the remaining combined qualification.

[Cold-build discovery session reuse](cold-build-performance.md) shares action-local
MSBuild sessions for framework negotiation and resolved-input export. Paired Orchard
exports remain byte-identical; full cold-workflow timing and runtime checks pass.
The cross-cold-build byte comparison retains the known Razor path-dependent output
limitation. Repeated compile-action staging and dependency validation remain the
next performance target.

[Compilation dependency staging](compile-staging-performance.md) now consumes
sealed Bazel dependency bundles directly and reuses validation within each action,
with complete integrity checks before publication. The final Orchard project has
byte-identical same-path outputs and a measured 16.8% median action-time reduction;
the full 202-project workflow improves 2.3% in single-run measurements and passes
runtime checks. NuGet source-copy costs and the independent-build Razor path
limitation remain; a further hash-reuse experiment was discarded without a clear
overall timing benefit.

## Orchard MSBuild phase attribution

See [MSBuild phase profiling](msbuild-phase-profile.md) for same-host raw SDK comparison,
plugin phase measurements and the Microsoft MSBuildCache implementation comparison.

## Validation reuse

[Validation reuse](validation-reuse.md) carries verified package hashes and sealed
entry validation through immutable lifetimes while retaining exit checks.

## One-pass replay placement

[Replay placement](replay-placement.md) preserves output membership while selecting
producer ownership once and eliminating overwritten copies and metadata parsing.

## Package-origin project outputs

[Package-origin outputs](package-origin-outputs.md) adds an opt-in sparse bundle
format backed by declared Bazel package inputs. Native remote recovery and sparse
dependency consumption pass. The Orchard entry/API pair omits 891 MB of duplicate
package files; runtime package over-fetch keeps the feature disabled by default.
