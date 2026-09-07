# Projects selected to fill coverage gaps

Source inspection: 2026-09-06. These selections extend the
[scenario mapping](scenario-coverage.md); all adapter experiments below are
**proposed**. No baseline, restore, package build or adapter execution was run for
this selection. Revisions pin the inspected source, not a validated toolchain.

## Selection summary

| Gap | Selected source | First experiment |
| --- | --- | --- |
| Different configurations of one dependency | dotnet/msbuild upstream graph fixtures | Separate configured nodes with different edge properties; converge only after removing the distinguishing property. |
| Ordinary, analyzer and build-order references | P16 CommunityToolkit.Mvvm | Build/test the Roslyn4001 slice with all required reference roles preserved. |
| Multi-targeting plus generation and conditional packages | P16 CommunityToolkit.Mvvm | Compare existing net472/net8 consumers on Windows, then introduce controlled package changes. |
| Source-built task consumed by another project | P05 Avalonia | Build/stage Avalonia.Build.Tasks and execute its XAML task in a separate source consumer. |
| Pack -> clean package consumer | P05 Avalonia BuildTests | Produce local packages, restore a fresh consumer, verify compiled XAML without producer access. |
| Additional task/runtime/Git interaction | P17 Nerdbank.GitVersioning | Later pilot: task closure and selected version-output integration tests. |

Apply the operation-specific C checks in the main mapping. Each slice gets its
own contract, test IDs and findings; source inspection cannot satisfy a K gate.

## CommunityToolkit.Mvvm (P16)

Pinned revision: `b135626dd54d33b8f05f2ff31591592c004aa848` in
[CommunityToolkit/dotnet](https://github.com/CommunityToolkit/dotnet/tree/b135626dd54d33b8f05f2ff31591592c004aa848).

The [Roslyn4001 test project](https://github.com/CommunityToolkit/dotnet/blob/b135626dd54d33b8f05f2ff31591592c004aa848/tests/CommunityToolkit.Mvvm.Roslyn4001.UnitTests/CommunityToolkit.Mvvm.Roslyn4001.UnitTests.csproj)
targets net472/net8/net9/net10. It references the MVVM library and external test
assembly normally, and the Roslyn4001 generator with `OutputItemType=Analyzer`
and `ReferenceOutputAssembly=false`. The
[library project](https://github.com/CommunityToolkit/dotnet/blob/b135626dd54d33b8f05f2ff31591592c004aa848/src/CommunityToolkit.Mvvm/CommunityToolkit.Mvvm.csproj)
has framework-conditioned packages, and on its netstandard2.0 inner build it
references generator/code-fixer projects with `ReferenceOutputAssembly=false`.
Their outputs are explicitly packed into Roslyn-version-specific analyzer paths.
These are packaging/build-order edges, not ordinary compiler references.

Selected experiments:

- **Build/Test:** export the actual configured graph and identify the normal,
  analyzer and packaging/build-order edges. On Windows, select existing net472
  and net8 test configurations, documenting the library framework each resolves.
  Confirm expected framework negotiation from the evaluated baseline; do not
  assume project-file target lists alone establish the selected graph.
- **Generation:** execute selected generated-property/command tests; mutate the
  generator and verify consumer invalidation while generator assemblies remain
  outside application runtime references. Inspect the generator API at this pin
  before assigning G01/G02. Retain shared projitems/import inputs.
- **Conditional packages:** choose a package reference already conditioned on the
  selected library framework. Record its resolved baseline version, then author
  an intentional version-change control with restore/re-export. Assert which
  configured nodes change. This mutation is new acceptance work, not an existing
  upstream test result.
- **Later Pack extension:** pack the library and generator payloads, restore a
  separate consumer from the local package and execute generated behavior. Select
  the intended Roslyn payload under a pinned compiler. This does not follow from
  project-reference tests alone.

Inventory toolchain pins, signing and all packaging prerequisites before builds.
A net8 Linux slice is useful independently; it does not prove net472 or all
frameworks. Keep Spectre.Console for its additional-file input behavior rather
than treating P16 as a replacement for every generator experiment.

## Avalonia (P05)

Pinned revision: `b709c58c6b1b8aa3b90866c7c001b7bf82b6353b` in
[AvaloniaUI/Avalonia](https://github.com/AvaloniaUI/Avalonia/tree/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b).
Track headless behavior, source tasks, package consumption and native rendering
as separate slices.

### Source-task slice

[BuildTargets.targets](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/build/BuildTargets.targets)
loads resource/XAML tasks from the source-build output of Avalonia.Build.Tasks
using TaskHostFactory. The
[XAML test consumer](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/tests/Avalonia.Markup.Xaml.UnitTests/Avalonia.Markup.Xaml.UnitTests.csproj)
imports those targets. The
[task project](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/src/Avalonia.Build.Tasks/Avalonia.Build.Tasks.csproj)
includes shared/submodule sources and package dependencies.

First inventory how upstream orchestration ensures the task is built. A UsingTask
path is evidence of consumption, not proof that ProjectGraph contains a producer
edge. Declare that scheduling/handoff requirement explicitly. Stage task DLLs,
dependencies and the task-host tool closure; remove the producer workspace and
run a selected compiled-XAML oracle. Mutating task source must invalidate the
consumer. A missing dependency must fail rather than load an ambient copy.

### Package-consumer slice

The [upstream build pipeline](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/nukebuild/Build.cs#L502)
depends on package creation, clears the build-test artifact directory, builds
Debug/Release consumers and verifies compiled XAML. Its
[NuGet configuration](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/tests/BuildTests/nuget.config)
uses a separate package cache and maps Avalonia packages to `artifacts/nuget`.
The [consumer project](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/tests/BuildTests/BuildTests/BuildTests.csproj)
imports shared test items and targets net10.0.

Start with this managed BuildTests consumer, not the entire workload-heavy
BuildTests solution. Preserve package creation/patching behavior needed for its
closure. Select required locally produced packages and their actual producer
commands; do not silently substitute published Avalonia packages. Restore outside
build actions into a fresh consumer cache, then remove producer/source-feed access
and verify compiled XAML from recovered artifacts. Use a declared verifier action;
record separate task-package and application output identities.

The upstream workflow is evidence of a useful test design, not of producer-free
isolation. The selected narrower pipeline still needs a baseline. Its
[F# consumer](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/tests/BuildTests/BuildTests.FSharp/BuildTests.FSharp.fsproj)
is a later F01 candidate; it does not establish a mixed C#/F# project-reference
graph. Native AOT, browser/mobile workloads and rendering remain separate stages.

## MSBuild configured-edge fixtures

Pinned revision: `fcb368d8894f6448382f20304c659f383d210f61` in
[dotnet/msbuild](https://github.com/dotnet/msbuild/tree/fcb368d8894f6448382f20304c659f383d210f61).
Use the fixtures as semantic references; this is not a proposal to build all of
MSBuild as the next application pilot.

[ProjectGraph_Tests.cs](https://github.com/dotnet/msbuild/blob/fcb368d8894f6448382f20304c659f383d210f61/src/Build.UnitTests/Graph/ProjectGraph_Tests.cs#L386)
includes different global-property entry/edge cases. Its fixture construction
uses `AdditionalProperties` to distinguish instances of a shared project and
`GlobalPropertiesToRemove` to converge downstream configurations.

Adapt these small graph shapes into executable acceptance fixtures with distinct
observable outputs. Preserve attribution and applicable license when copying
source. Test C07 configured-node identity, C13 matching replay properties and C14
regeneration when edge properties change. Include incompatible-property rejection
as an authored negative control. Graph-construction tests alone do not establish
SDK restore, compilation or replay semantics; add each deliberately under the
pinned adapter SDK.

## Nerdbank.GitVersioning (P17)

Pinned revision: `700f125382c10bb149e52df4fc8513a86886c8ef` in
[dotnet/Nerdbank.GitVersioning](https://github.com/dotnet/Nerdbank.GitVersioning/tree/700f125382c10bb149e52df4fc8513a86886c8ef).
Keep this as the later task-focused pilot, after P05 establishes the task handoff
contract.

The [Tasks project](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/src/Nerdbank.GitVersioning.Tasks/Nerdbank.GitVersioning.Tasks.csproj)
targets net472/net8 and references its implementation library. The
[test project](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/test/Nerdbank.GitVersioning.Tests/Nerdbank.GitVersioning.Tests.csproj)
references Tasks/library normally and the nbgv tool with
`ReferenceOutputAssembly=false` for net10, recording its output path for tests.
[Integration tests](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/test/Nerdbank.GitVersioning.Tests/BuildIntegrationTests.cs)
exercise version target results and generated version information.

Inventory the LKG/bootstrap versioning package, Git state, native dependencies,
MSBuild loading and hard-coded output paths before choosing test methods. Then
build/stage the task closure and executable tool, run controlled Git/version
cases and compare target results with ordinary MSBuild. Selected integration tests
invoke MSBuild by design: record those invocations as the task-behavior oracle;
do not confuse them with accidental rebuilding by a consumer runtime test. Pack
and Framework lanes remain later extensions.

## Remaining selections and coverage assignments

The following sources fill the remaining identified categories. All are proposed
experiments based on source inspection; no new support or passing tests are
claimed. Framework/workload/tool versions must be resolved from each pinned
source before defining a runnable baseline.

| Scenario / check | Selected source | Initial lane and boundary |
| --- | --- | --- |
| F13; C06/C07/C13/C14 | MSBuild solution-graph tests and MSBuildSdks solution/traversal tests | Linux x86-64 for portable fixture shapes; verify each requested solution format under the pinned toolchain. |
| F14; C03/C08/C09/C14 | MSBuildSdks Traversal/NoTargets and MSBuild SDK resolver tests | Package SDK plus explicit local SDK fixture; acquisition outside build actions. |
| F15; C05/C06/C07/C08 | dotnet/sdk Clean tests and MSBuildSdks Clean/Rebuild tests | Native Linux fixture first; separate Windows extension. |
| F01; C01/C07/C13 | dotnet/sdk AppWithLibraryVB | SDK-style VB app/library; mixed C#/VB is a separately authored extension. |
| F02; F04; C01/C05/C13 | MSBuild non-SDK dependency fixture, SDK legacy VB template and NuGet.Client restore fixtures | Windows with the named Framework targeting/build/runtime tools. |
| P18; C01/C05/C09/C15 | dotnet/blazor-samples server-interactive sample | Linux x86-64 server plus pinned browser; no external identity provider needed for the selected interaction oracle. |
| F11 | dotnet/project-system target tests, then Visual Studio integration tests | Design-time outputs first; actual IDE behavior on a declared Windows/Visual Studio environment. |
| C10 | Existing diamond, then P01 Serilog, with bazel-remote | Two independent compatible Linux workers; shared remote cache only. |
| C11 | Existing diamond, then P01 Serilog, with Buildbarn | Remote Linux execution with declared .NET toolchain/runtime closure; no local fallback. |

## Solution orchestration (F13)

Use MSBuild revision `fcb368d8894f6448382f20304c659f383d210f61` and MSBuildSdks
revision `60e5aa0dabf1e6276f2b698337a6dc92620c05ec`.
[GraphLoadedFromSolution_tests.cs](https://github.com/dotnet/msbuild/blob/fcb368d8894f6448382f20304c659f383d210f61/src/Build.UnitTests/Graph/GraphLoadedFromSolution_tests.cs)
contains project-specific configuration mapping, solution-injected dependency
edges and controls against overwriting project-reference/multi-targeting edges.
[SolutionTests.cs](https://github.com/microsoft/MSBuildSdks/blob/60e5aa0dabf1e6276f2b698337a6dc92620c05ec/src/Traversal.UnitTests/SolutionTests.cs)
includes skipped-project behavior.

Adapt those graph shapes into a small executable app/library fixture. Compare
traversal and solution entry points only when they intentionally encode equivalent
semantics. Test differing project configurations, exclusions and solution-only
edges independently; record expected nodes, edge kinds and output identities.
Then change a solution mapping and require plan regeneration before analysis.

Assign separate cases to .sln, .slnx and solution filters where the chosen toolchain
supports them. Source inspection here does not establish that every format is
covered by the cited tests or supported by the adapter's pinned SDK. Unsupported
formats must be rejected or remain outside the claim, not silently interpreted as
equivalent input. NuGet solution-filter restore tests below supply an additional
restore-side reference, not graph-execution evidence.

## Custom SDK resolution (F14)

Use MSBuildSdks revision `60e5aa0dabf1e6276f2b698337a6dc92620c05ec`.
The [Traversal sample](https://github.com/microsoft/MSBuildSdks/blob/60e5aa0dabf1e6276f2b698337a6dc92620c05ec/samples/Traversal/dirs.proj)
explicitly names `Microsoft.Build.Traversal/4.1.82` and references two projects.
[NoTargets SDK sources](https://github.com/microsoft/MSBuildSdks/tree/60e5aa0dabf1e6276f2b698337a6dc92620c05ec/src/NoTargets/Sdk)
provide another bounded SDK implementation to inspect.

Use the sample's package SDK as the first resolver experiment. Inventory and hash
resolved SDK props/targets and resolver/tool inputs; mutate the SDK version or
imports with fresh preparation and assert expected graph/action invalidation.
Missing or mismatched SDK inputs must fail without an ambient resolver fallback.
A package version change is an authored experiment and needs independently pinned
package identities; the repository commit does not pin all acquired binaries.

For local SDK/resolver semantics, adapt selected
[SdkResolverService_Tests.cs](https://github.com/dotnet/msbuild/blob/fcb368d8894f6448382f20304c659f383d210f61/src/Build.UnitTests/BackEnd/SdkResolverService_Tests.cs)
fixtures at MSBuild revision `fcb368d8894f6448382f20304c659f383d210f61`. Tests include
unresolved SDKs, version mismatches, resolver state and returned paths/properties/
items. Create a declared repository-local SDK fixture for actual evaluation and
execution. Mock resolver tests alone do not prove package acquisition, SDK
relocation or adapter isolation.

## Clean and Rebuild (F15)

Use dotnet/sdk revision `fcd632a06320edcb05ac62f20e150da48b00b6a8`.
[GivenThatWeWantToCleanAProject.cs](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/test/Microsoft.NET.Clean.Tests/GivenThatWeWantToCleanAProject.cs)
includes cleaning without an assets file and `Clean;Build` behavior. At MSBuildSdks
revision `60e5aa0dabf1e6276f2b698337a6dc92620c05ec`,
[TraversalTests.cs](https://github.com/microsoft/MSBuildSdks/blob/60e5aa0dabf1e6276f2b698337a6dc92620c05ec/src/Traversal.UnitTests/TraversalTests.cs)
includes Clean/Rebuild target propagation and static-graph target mappings.

Before implementation, define ownership of source-workspace outputs, restored
metadata, adapter staging and Bazel-managed outputs. Clean is a state-changing
operation whose deletions must not be skipped by an action-cache hit; it is not a
cacheable artifact producer. Do not edit Bazel cache internals to implement it.
Specify whether the public Rebuild operation forces compiler execution or permits
artifact recovery, and compare ordinary MSBuild only under the matching declared
semantics. Record that decision in the operation contract rather than assuming
that a Bazel cache hit means an MSBuild Rebuild target executed.

Author independent cases for Build -> Clean -> Build, Build -> Rebuild, cleaning
one supported configuration while preserving another, removal of stale generated
outputs and recovery from the retained disk cache. Keep cache purge distinct from
output cleanup. Upstream tests provide target behavior references, not this new
adapter-facing command contract.

## VB and traditional Framework projects (F01/F02)

Use dotnet/sdk revision `fcd632a06320edcb05ac62f20e150da48b00b6a8`.
[AppWithLibraryVB](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/test/TestAssets/TestProjects/AppWithLibraryVB/TestApp/TestApp.vbproj)
is an SDK-style executable referencing a VB library. Resolve its
`CurrentTargetFramework` from the test harness, preserve language-specific inputs
and execute the app after recovery. Add a C# consumer as a separate mixed-language
fixture; a VB-to-VB graph does not establish that interaction.

For classic project syntax, MSBuild revision
`fcb368d8894f6448382f20304c659f383d210f61` has a
[NonSdkProjectWithDependencies entry point](https://github.com/dotnet/msbuild/blob/fcb368d8894f6448382f20304c659f383d210f61/src/MSBuild.EndToEnd.Tests/TestAssets/NonSdkProjectWithDependencies/ConsoleApp/ConsoleApp.csproj)
targeting Framework 4.7.2 with two project dependencies and explicit common/C#
imports. The SDK's
[legacy VB project template](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/test/TestAssets/ProjectConstruction/NetFrameworkProjectVB/NetFrameworkProject.vbproj)
uses classic syntax, Framework 4.5.2 and explicit VisualBasic targets. It is a
construction template, not a verified standalone executable; instantiate it under
an explicit Windows targeting-pack contract without silently retargeting it.

Keep packages.config as a distinct restore extension. At NuGet.Client revision
`5fe0c128b2d58335a60161c5141064be42dd8a6b`,
[NuGetRestoreCommandTest.cs](https://github.com/NuGet/NuGet.Client/blob/5fe0c128b2d58335a60161c5141064be42dd8a6b/test/NuGet.Clients.Tests/NuGet.CommandLine.Test/NuGetRestoreCommandTest.cs)
generates local packages, packages.config inputs, two-project solutions and
solution filters. Adapt selected restore cases, then integrate them with an
executable legacy fixture. Declare package assembly references and imports as
well as restore files; restoration alone does not prove the package is used by
compilation or the recovered runtime. Package upgrades and missing-asset controls
remain authored acceptance work.

## Server-side Blazor (P18)

Pinned revision: `567732e0a78d2c1b2a22c3677f86c673d7527bed` in
[dotnet/blazor-samples](https://github.com/dotnet/blazor-samples/tree/567732e0a78d2c1b2a22c3677f86c673d7527bed).
Select
[10.0/BlazorSample_BlazorWebApp/BlazorSample.csproj](https://github.com/dotnet/blazor-samples/blob/567732e0a78d2c1b2a22c3677f86c673d7527bed/10.0/BlazorSample_BlazorWebApp/BlazorSample.csproj),
a net10 web project with a QuickGrid package reference. Its
[Program.cs](https://github.com/dotnet/blazor-samples/blob/567732e0a78d2c1b2a22c3677f86c673d7527bed/10.0/BlazorSample_BlazorWebApp/Program.cs)
registers interactive server components and the interactive server render mode.

Build/publish the upstream app, recover it into a fresh runtime workspace, start
the server without build/restore and drive a selected local interactive component
from a pinned browser. Verify the server circuit and observable state change;
an HTTP 200 or prerendered HTML alone cannot establish interactivity. Declare
endpoint, HTTPS/certificate and runtime configuration used by the test. Choose
local component interactions that do not require an external identity provider
or unrelated sample services. Connection loss/reconnect is a later explicit test.

This is separate from P09's WebAssembly and WebAssembly AOT stages. The larger
[ASP.NET Core per-page sample](https://github.com/dotnet/aspnetcore/blob/0b5b41b76d74fa93c86de07eb69775668c0b1c17/src/Components/Samples/BlazorWebAppPerPage/Program.cs)
was also inspected: it enables both server and WebAssembly modes, but its
repository-specific framework references add bootstrapping requirements. Keep it
as a later mixed-render-mode candidate rather than the first server-side baseline.

## Design-time and IDE behavior (F11)

Pinned revision: `1379b2dce76234664ad1b970e0bd72dc95c75e68` in
[dotnet/project-system](https://github.com/dotnet/project-system/tree/1379b2dce76234664ad1b970e0bd72dc95c75e68).
[DesignTimeTargetsTests.cs](https://github.com/dotnet/project-system/blob/1379b2dce76234664ad1b970e0bd72dc95c75e68/tests/Microsoft.VisualStudio.ProjectSystem.Managed.UnitTests/ProjectSystem/DesignTimeTargets/DesignTimeTargetsTests.cs)
checks design-time target evaluation/build. Start with a supported C# fixture and
compare declared design-time references, source items and compiler options after
ordinary build versus adapter recovery. Pin the design-time targets and globals
separately from Build; do not replay ordinary Build results as design-time results.

The [OpenProject tests](https://github.com/dotnet/project-system/blob/1379b2dce76234664ad1b970e0bd72dc95c75e68/tests/Microsoft.VisualStudio.ProjectSystem.IntegrationTests/OpenProjectTests.cs)
wait for IntelliSense and build projects. The
[dependency-node tests](https://github.com/dotnet/project-system/blob/1379b2dce76234664ad1b970e0bd72dc95c75e68/tests/Microsoft.VisualStudio.ProjectSystem.IntegrationTests/DependencyNodeIntegrationTests.cs)
exercise frameworks, packages and project references. Use these as a later
Windows/Visual Studio integration lane with the IDE/version/workloads declared.
Target-output tests alone do not prove IntelliSense, generated-document visibility,
debugging or watch/hot reload; those remain separately scoped F11 extensions.

## Independent remote workers (C10/C11)

These select infrastructure and an initial workload, not another application
portfolio entry. Start with the existing package-free diamond, then extend to P01
Serilog only after its local adapter support passes. Current local-only adapter
restrictions stay in place until the remote capability contract and tests exist.
No remote services have been deployed or worker behavior measured here.

### Remote cache

Select [bazel-remote](https://github.com/buchgr/bazel-remote/tree/a69b6b5ed933234d93b489ffd216bee5bb74aa06)
at revision `a69b6b5ed933234d93b489ffd216bee5bb74aa06`. It provides HTTP/gRPC remote
cache service. Pin the built binary/container digest and configuration separately
before execution; a source revision alone does not pin a deployment image.

Worker A publishes results. Worker B uses the same declared compatible platform
and toolchain, a separate checkout and empty local build caches/output base, with
no producer workspace access. Require remote hits, zero compilation for the
recovery case and correct application output. Retain client/server evidence so
local reuse cannot masquerade as a remote hit. Change a toolchain/platform
identity in a separate control and prove incompatible entries are not reused;
local rebuilding is permitted in this remote-cache experiment.

### Remote execution

Select [Buildbarn bb-deployments](https://github.com/buildbarn/bb-deployments/tree/a35485609467dd70cd44c78b4735e5835061df5a)
at revision `a35485609467dd70cd44c78b4735e5835061df5a`. Its deployment examples provide
a starting point for remote execution. Inventory and pin all service/worker
images and configuration, then provision the declared .NET compiler/runtime and
native dependency closure on a Linux worker.

Force action identities absent from enabled caches and require actual remote
execution, not merely remote cache hits. Disable local fallback for this test;
retain worker/client execution logs and run the recovered App. Worker inputs may
include the explicitly provisioned toolchain but must not depend on producer
bin/obj, undeclared package caches or compilation-time acquisition. Remove a
required tool/runtime input and require an explicit failure. Deployment on one
host is useful smoke testing; it does not replace the independent-worker evidence
needed for the stated C10/C11 claims.

## Multi-language harness scope (P07/R12)

The Aspire selection uses existing Bazel language support:
[rules_python](https://github.com/bazel-contrib/rules_python),
[rules_js](https://github.com/aspect-build/rules_js) and
[rules_ts](https://github.com/aspect-build/rules_ts) as appropriate. Their versions
and compatibility with the adapter's pinned Bazel must be established before use;
these links identify upstream implementations, not validated dependency pins.

Build a small shared .NET/Python/TypeScript harness first, wiring upstream-rule
targets to the MSBuild adapter's outputs. Test runfiles/runtime handoff, common
orchestration, language-local edits, shared-schema edits and cache recovery.
Then integrate those targets into Aspire startup/readiness and end-to-end tests.
Python/Node toolchains, package resolution and compilation stay with the existing
rules; our work is the .NET integration and harness glue. No new Python or
TypeScript build-rule implementation is planned.
