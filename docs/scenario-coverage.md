# Scenario and coverage mapping

Planning snapshot: 2026-09-06. This portfolio tests whether Bazel can schedule and
cache configured project builds while MSBuild retains SDK, NuGet and project
semantics. It complements the [roadmap](roadmap.md),
[real-project pilot](real-project-pilot.md) and [risk register](edge-cases-and-risks.md).

A project name is a candidate for an experiment, not a compatibility claim.
Coverage belongs to a pinned subtree, configuration, platform, command and
observable result. Preserve upstream behavior; do not remove generators, signing,
imports or dependencies to make a candidate pass.

## Status and evidence

| Status | Meaning |
| --- | --- |
| Measured adapter slice | Linked findings record actual isolated adapter execution for the stated boundary. |
| Ordinary baseline only | Upstream MSBuild build/test has run; adapter support is not established. |
| Contract only | Acceptance is specified, but passing implementation evidence is absent. |
| Proposed | Candidate and acceptance goal selected for planning; baseline and adapter execution remain to be done. |
| Gap | A scenario needs a focused fixture or an explicitly selected project. |

Current measured foundations are deliberately narrower than this portfolio:

| Foundation | Evidence and boundary |
| --- | --- |
| Explicit Shared -> App adapter | [Bazel findings](bazel-findings.md), [replay](replay-findings.md), [identity](action-identity-findings.md) and [staging](staging-findings.md): isolated builds, dependency handoff and bounded local cache/relocation controls. Consult each record for platform and command details. |
| Package payloads | [Build packages](package-input-findings.md) and [managed binary packages](binary-package-findings.md): selected package input and runtime-asset cases in the explicit adapter; not general NuGet or generated-graph package support. |
| Runtime inputs | [Native runtime](native-runtime-findings.md), [integrity](native-runtime-integrity-findings.md) and [loaded JIT](loader-runtime-findings.md): bounded runtime declarations and substitution/rejection evidence; full host closure remains open. |
| Configured graph export/execution | [Export findings](graph-export-findings.md) and [execution findings](graph-execution-findings.md): first package-free Release/net10.0 execution slice measured on macOS ARM64. Do not extend its platform or cache claims beyond the linked evidence. |
| Generated-graph cache matrix | [Cache contract](graph-cache-contract.md): contract only; the missing probe leaves acceptance intentionally red. |
| Serilog | [Pilot findings](real-project-pilot.md): pinned ordinary MSBuild baseline and one API approval test on macOS ARM64; no adapter execution yet. |

## Operation boundaries

Coverage is recorded per operation. The following are proposed contracts; a
project passing one operation does not establish support for the others.

| Operation | Declared inputs -> outputs | Execution and cache policy |
| --- | --- | --- |
| Prepare | Source/evaluation inputs, tool pins, restore configuration and lock state -> restored payloads and configured graph/input manifests | Acquisition may use the network. Record discovery dependencies, including globs and absent optional imports. Revalidate before using a plan; preparation caching needs its own identity contract. |
| Build | Configured project inputs, compiler/tool closure and dependency results/artifacts -> named build artifacts and replay results | One configured project build per action in the supported slice; dependency compilation must not occur inside consumers. Validate local cache recovery independently. |
| Publish / Pack | Selected build outputs plus operation-specific metadata, assets and tools -> runnable distribution or package | Separate requested targets and artifact contract. Declare intentional AOT/linker/asset-generation work; identify any managed recompilation required by changed publish properties. Do not assume Build artifacts are sufficient. |
| Test | Built test/runtime closure, test data, runner and environment -> result/log artifacts | Run without implicit build/restore. Start with uncached test execution; cache test results only after a separate isolation and input-completeness contract. |
| Launch | Recovered application artifacts, configuration and service resources -> observable running behavior | No cache of running services. Start fresh services and verify readiness/behavior; compilation or restore during launch fails the artifact-only acceptance check. |
| Design-time (F11) | Source/evaluation state and declared IDE targets/options -> design-time references/items/compiler options | Separate target/result contract from Build. Target evaluation is not IDE integration evidence; begin uncached. |
| Clean / Rebuild (F15) | Selected output ownership and configuration -> changed local state and, for Rebuild, requested rebuilt/recovered artifacts | Clean deletions must execute and are not a cacheable artifact. Define Rebuild force-execution versus recovery semantics before implementation; keep cache purge separate. |

The operation and requested target set belong to the action contract; project
path plus global properties still identifies the configured project node.

## Project portfolio

All rows below are **proposed adapter coverage**. Serilog additionally has the
ordinary baseline above. Spectre.Console has a pinned source inspection in the
pilot document. The [selected coverage extensions](coverage-project-selections.md)
pin source inspections for CommunityToolkit.Mvvm, Avalonia, Nerdbank.GitVersioning,
server-side Blazor, upstream build/IDE fixtures and remote infrastructure. These pins do not establish compatible toolchains or build
results. Other candidates still need revisions. Upstream branch links below are
discovery references; use the pinned selection records for those experiments.

| ID | Scenario | Candidate / bounded entry point | What acceptance must demonstrate |
| --- | --- | --- | --- |
| P01 | Real library, packages, signing, resources, multi-targeting | [Serilog](https://github.com/serilog/serilog): approval-test project and library | Preserve configured inner/outer-build semantics, PolySharp, signing and shared imports; match API approval and add a logging-behavior oracle. |
| P02 | Generator built in the same graph; additional data inputs | [Spectre.Console](https://github.com/spectreconsole/spectre.console): Console/Ansi and their generator | Build and stage analyzer-project output before consumers; declare JSON additional inputs and generator dependencies; recover generated outputs correctly. |
| P03 | Deeper managed provider graph | [EF Core](https://github.com/dotnet/efcore): Core/Relational, then selected SQLite provider tests | Correct shared dependency scheduling and selective rebuilds; include native SQLite only when explicitly added to the closure. |
| P04 | Modular ASP.NET application, Razor, themes and web assets | [Orchard Core](https://github.com/OrchardCMS/OrchardCore): small host with selected source modules | Recovered app discovers modules, renders expected pages and serves built assets; pin the frontend build tools and inputs. |
| P05 | Desktop XAML, source-built tasks and package consumption | [Avalonia](https://github.com/AvaloniaUI/Avalonia): separate headless, source-task and BuildTests package slices | Compile XAML and preserve resources; build/stage source tasks and their dependencies; pack into a local feed and verify a clean package consumer. Track each slice independently; native rendering remains separate. See [selection details](coverage-project-selections.md#avalonia-p05). |
| P06 | Large repository and independent service families | [Azure SDK for .NET](https://github.com/Azure/azure-sdk-for-net): selected core/storage slices, then a second family | Preserve actual package/project edges and linked shared sources; unrelated service edits reuse outputs. Use mock tests first, then pinned playback assets/proxy. |
| P07 | Mixed-language composition and multiple services | [Aspire polyglot task queue](https://github.com/microsoft/aspire-samples/tree/main/samples/polyglot-task-queue) | Compose C#, Python and TypeScript/Node outputs with RabbitMQ; start recovered services and verify a complete task flow without hidden restore or compilation. |
| P08 | Native AOT executable publishing | [ConsoleAppFramework](https://github.com/Cysharp/ConsoleAppFramework): NativeAotTests | Build generator and managed closure, publish with declared AOT compiler/linker/runtime packs, then execute the recovered native program without a .NET runtime. |
| P09 | Razor component library, static web assets and Blazor WebAssembly | [MudBlazor](https://github.com/MudBlazor/MudBlazor): library and a small consuming app, then Docs.Wasm | Compile Razor and frontend assets; browser smoke test recovered output. Add WebAssembly AOT publishing as a separate experiment, not an assumed default. |
| P10 | Modern .NET WPF | [MaterialDesignInXamlToolkit](https://github.com/MaterialDesignInXAML/MaterialDesignInXamlToolkit): selected library/demo, net10.0-windows | Windows XAML/BAML, resources, markup compilation and recovered-app smoke test. |
| P11 | .NET Framework WPF | Same toolkit, existing net462 target and compatible host | Framework targeting/reference assemblies and Windows runtime behavior; keep distinct from the modern .NET lane. |
| P12 | Modern .NET WinForms | [Krypton Standard Toolkit](https://github.com/Krypton-Suite/Standard-Toolkit): toolkit and TestForm, net10.0-windows | Resource/designer-generated source build, dependency staging and recovered-app smoke test on Windows. |
| P13 | .NET Framework WinForms | Same toolkit and compatible TestForm configuration, net48 | Framework-specific references and runtime assets; separate baseline and cache identity from modern .NET. |
| P14 | Interceptor-based source generation | [Dapper.AOT](https://github.com/DapperLib/DapperAOT): small instrumented consumer | Prove the generated interceptor handles the call; source-location edits and relocation cannot leave stale call-site bindings. Native AOT publishing is optional and separate here. |
| P15 | Long-term runtime repository integration | [dotnet/runtime](https://github.com/dotnet/runtime): selected managed library subtree, eventually native components | Begin with pinned bootstrap/toolchain and managed dependencies; later add native shims, CMake/compiler inputs and runtime-specific configuration dimensions. No whole-repository claim from a library slice. |
| P16 | Mixed reference roles, configured frameworks and generator/package interactions | [CommunityToolkit.Mvvm](https://github.com/CommunityToolkit/dotnet): Roslyn4001 tests, MVVM library and generator/code-fixer projects | Preserve ordinary, analyzer and packaging/build-order edges; verify framework-specific dependencies and generated behavior. Package consumption is a separate extension. See [selection details](coverage-project-selections.md#communitytoolkitmvvm-p16). |
| P17 | Later task-focused pilot with Git-derived inputs | [Nerdbank.GitVersioning](https://github.com/dotnet/Nerdbank.GitVersioning): Tasks/library and selected integration tests | Build/stage the task closure, preserve the nbgv build-order edge and check version outputs against controlled Git state. Later pilot; native assets and bootstrap/versioning inputs require inventory. See [selection details](coverage-project-selections.md#nerdbankgitversioning-p17). |
| P18 | Server-side interactive Blazor | [dotnet/blazor-samples](https://github.com/dotnet/blazor-samples): net10 BlazorSample_BlazorWebApp | Publish/recover the app, establish a server circuit and verify browser-driven state changes; keep distinct from WebAssembly and static HTML. See [selection details](coverage-project-selections.md#server-side-blazor-p18). |

The desktop portfolio covers SDK-style projects targeting both modern .NET and
.NET Framework. That does **not** cover traditional non-SDK project formats or
packages.config. Those remain a separate gap below.

## Generator coverage

Generator implementation and generated behavior are independent axes. Both
classic `ISourceGenerator` and incremental `IIncrementalGenerator` need a defined
support policy. Interceptors are a generated-code/compiler feature, not a third
generator API. Roslyn incremental computation reuse is separate from Bazel action
cache reuse; cold compiler processes must still produce correct results.

| ID | Axis / case | Proposed coverage | Required oracle or perturbation |
| --- | --- | --- | --- |
| G01 | Classic generator API | Small pinned `ISourceGenerator` fixture | Generated API is consumed and executes; fresh process, changed input and removed input behave correctly. |
| G02 | Incremental generator API | Small pinned fixture plus ordinary generation in the portfolio | Change relevant syntax/symbols and additional inputs; compare cold execution with recovered artifacts. Pin and inspect the actual implementation before assigning a project to this cell. |
| G03 | Ordinary generated types/methods | System.Text.Json serialization-context consumer | Serialization/deserialization proves generated code is usable; do not silently fall back to reflection in the oracle. |
| G04 | Interceptor-emitting generator | P14 Dapper.AOT | Prove interception executes; move checkout, rename file, insert lines, change/remove call and verify fresh and recovered behavior. |
| G05 | Generator delivered by NuGet | P01 PolySharp plus P14 | Declare generator DLLs, their dependency closure and compiler/analyzer configuration; package upgrades invalidate consumers. |
| G06 | Generator delivered by project reference | P02 Spectre.Console, P08 ConsoleAppFramework and P16 CommunityToolkit.Mvvm | Preserve `OutputItemType=Analyzer` / `ReferenceOutputAssembly=false` semantics; generator changes rebuild consumers without becoming application runtime references. |
| G07 | Non-source inputs | Focused fixture and P02 | Perturb AdditionalFiles, .editorconfig/global analyzer config, compiler-visible properties and options independently. |
| G08 | Generated file lifecycle and diagnostics | Focused fixture across G01–G04 | Removed inputs remove stale generated output; diagnostics survive; optional emitted files do not become undeclared inputs on the next build. |
| G09 | Compiler/feature compatibility | P14 and focused version controls | Include SDK/Roslyn, language version and interceptor opt-ins in identity; incompatible combinations fail explicitly. |
| G10 | Generator supplied by SDK/framework tooling | G03 serialization-context fixture with its resolved generator origin recorded | Inventory the actual generator assembly and dependencies; SDK/reference-pack changes invalidate consumers even without a generator PackageReference. |
| G11 | Diagnostic analyzer without emitted code | Small analyzer fixture, delivered as package and project reference | Change rules, severity, suppressions and warnings-as-errors; verify diagnostics and exit status on fresh execution and cache recovery. A prior successful build must not mask a newly failing diagnostic. |

Current Roslyn interceptor location encoding includes source content checksum and
position information. Do not assume all versions use absolute file paths, or that
path mapping alone proves portability. Pin the compiler/generator pair and test
its actual location scheme. Sources: [Roslyn generator APIs](https://github.com/dotnet/roslyn/blob/main/docs/features/source-generators.md),
[incremental generators](https://github.com/dotnet/roslyn/blob/main/docs/features/incremental-generators.md),
[interceptors](https://github.com/dotnet/roslyn/blob/main/docs/features/interceptors.md),
[System.Text.Json generation](https://learn.microsoft.com/en-us/dotnet/standard/serialization/system-text-json/source-generation),
[Dapper.AOT usage](https://aot.dapperlib.dev/gettingstarted).

## Aspire composition boundary

P07 needs a composition model beyond MSBuild ProjectGraph. Use the MSBuild adapter
for .NET builds and integrate existing Bazel rules for Python and TypeScript/Node
through shared multi-language harnesses. Reuse rules_python and appropriate
rules_js/rules_ts targets; pin compatible versions rather than implement new
language rules. The harness owns target wiring, runfiles/artifact handoff, test
orchestration and shared cache/invalidation evidence.
Aspire describes application resources, startup/readiness and connection wiring;
a runtime service relationship is not automatically a compile dependency.

Record build edges, generated-contract edges and runtime relationships separately.
A C# implementation edit should not rebuild unrelated Python/TypeScript outputs;
a frontend edit should not rebuild an unrelated worker; a shared schema edit must
invalidate its actual generated consumers. Acquire pinned packages, tools and
container images during preparation. Recover every language's artifacts before
launching and test the end-to-end message flow. This does not require running the
whole distributed application inside a per-project compilation sandbox.

## Gaps best covered by focused fixtures

These are proposed coverage additions, not requirements to adopt another large
repository for every row.

| ID | Missing scenario | First experiment / acceptance boundary |
| --- | --- | --- |
| F01 | F# and VB; mixed managed-language graph | Selected: SDK AppWithLibraryVB and later Avalonia F# consumer. Add C# consumers as separately authored mixed-language graph tests; preserve language inputs and handoff. [Selections](coverage-project-selections.md#vb-and-traditional-framework-projects-f01f02). |
| F02 | Traditional .NET Framework projects | Selected: MSBuild non-SDK dependency fixture, SDK legacy VB template and NuGet.Client packages.config restore fixtures. Integrate restore with executable consumers as a separate test on declared Windows tools. [Selections](coverage-project-selections.md#vb-and-traditional-framework-projects-f01f02). |
| F03 | Native interop and RID selection | P/Invoke consumer with RID-specific native package assets, then a source-built native library; check actual loading. C++/CLI is a separate Windows extension if required. |
| F04 | NuGet restore semantics | Central versions, locks, conditions/conflicts and asset metadata. R02 adds PrivateAssets default/all/none controls; R07 expands categories and IncludeAssets/ExcludeAssets interactions. Compare local versus transitive inputs, metadata-only invalidation and F05 packed dependency metadata; record the selected closure per consumer. |
| F05 | Pack and independent consumption | P05 Avalonia BuildTests is the first selected package consumer; verify compiled XAML from locally produced packages. P16 analyzer-package consumption is a separate extension. Neither proves every native/build/analyzer asset variant. |
| F06 | Publish variants | Framework-dependent, self-contained, single-file, trimmed and ReadyToRun outputs; run recovered output. Native AOT and WebAssembly AOT retain separate P08/P09 lanes. |
| F07 | Resources and dynamic runtime behavior | Satellite assemblies/cultures, embedded resources, copied content and plugin loading; verify discovery at runtime after relocation. |
| F08 | External code-generation tools | Protobuf/OpenAPI or small custom tool; declare executable, schema, templates and outputs; test deletion and version changes. |
| F09 | Custom MSBuild tasks and target ordering | P05 source-task slice, then P17: build the task closure and execute it in a separate consumer. Declare task-loading and scheduling edges; extend separately to generated imports and target-order controls. |
| F10 | Git-derived versioning and signing | Explicit Git/version inputs, SourceLink/PDB paths and signing inputs; distinguish deterministic build signing from external release-signing operations. |
| F11 | IDE/design-time and developer loop | Selected: project-system design-time target tests, then Windows/Visual Studio OpenProject and dependency-node tests. Debugging, generated-document visibility and watch/hot reload remain separate extensions. [Selections](coverage-project-selections.md#design-time-and-ide-behavior-f11). |
| F12 | Mobile/workload SDKs | MAUI Android/iOS only if brought into scope; pin workloads/platform SDKs and separate build, simulator/device execution and signing. |
| F13 | Solution entry points and orchestration | MSBuild solution graph plus MSBuildSdks solution/traversal fixtures: configuration mappings, exclusions and solution-only dependencies. .sln/.slnx/filter support each needs evidence. [Selection](coverage-project-selections.md#solution-orchestration-f13). |
| F14 | Custom SDK resolution | MSBuildSdks package SDK sample plus MSBuild resolver/local SDK fixtures: version/import mutations, missing SDKs and no ambient fallback. [Selection](coverage-project-selections.md#custom-sdk-resolution-f14). |
| F15 | Clean/Rebuild and output ownership | SDK Clean and Traversal Clean/Rebuild fixtures; define command semantics before testing configuration preservation, stale-output removal and cache recovery. [Selection](coverage-project-selections.md#clean-and-rebuild-f15). |

## Acceptance matrix shared across scenarios

The project-to-check table below assigns required local checks. Each check must
have an executable test ID before its slice can be marked measured. Existing
two-project results are controls, not automatic proof for the real-project
portfolio. C10 and C11 are separately promoted remote capabilities.

| ID | Check | Evidence to retain |
| --- | --- | --- |
| C01 | Ordinary baseline versus adapter | Identical selected configuration and declared output comparison; executable test, API, UI or browser oracle appropriate to the scenario. |
| C02 | Fresh isolated execution | Empty outputs/cache, action logs, native sandbox strategy and declared inputs; no dependency managed compilation hidden inside Build consumers. Publish records its intentional compilation/linking separately. |
| C03 | Unchanged and selective edits | Expected versus actual executed action set for leaf, shared source, imports, package/generator/tool versions and configuration changes. |
| C04 | Implementation-only versus public API edit | State the invalidation policy first. Conservative dependent rebuilds can be correct; reference-assembly-based reuse needs distinct evidence. |
| C05 | Local cache recovery and relocation | Delete outputs, use a fresh output base/checkout, remove producer access and run recovered artifacts; verify permissions and required metadata. |
| C06 | Graph mutation and stale outputs | Add/remove/rename projects, edges and sources; regenerate graph before analysis and ensure obsolete outputs cannot satisfy consumers. |
| C07 | Configuration and concurrency | Multiple TFMs, Debug/Release, RIDs, architectures and relevant globals remain distinct; simultaneous builds cannot collide in output/staging paths. |
| C08 | Failure and interruption | Missing/corrupt/stale bundles, failed generators/tasks and interrupted writes cannot publish usable partial cache entries; recovery is explicit. |
| C09 | Ambient inputs | Perturb checkout path, environment, locale/timezone, timestamps and declared Git metadata; identify filesystem case/symlink assumptions and host reads. |
| C10 | Independent-worker remote cache | Compatible worker recovers without producer state; incompatible toolchain/platform identities reject reuse. Local cache hits do not establish this. |
| C11 | Remote execution | Empty worker plus declared toolchain/runtime closure executes without undeclared network/filesystem dependencies. Separate gate from remote caching. |
| C12 | Performance and reproducibility | Repeated cold, warm, edited and recovered runs; report restore/setup separately, cache/host state, action counts and timings. Distinguish byte equality from behavioral equivalence. |
| C13 | Dependency-result and artifact handoff | Capture requested targets, globals, returned items/metadata and artifacts. Exercise preparation-input integrity, generated-output recovery, materialized-bundle validation, forced replay and valid producer-result changes using the protocol below. Compare consumer-visible results with ordinary MSBuild; require execution evidence for the path under test. |
| C14 | Discovery and preparation invalidation | Independently add a globbed source, create an absent optional import and toggle a condition selecting a dependency. Show old/new evaluated inputs and edges, preparation regeneration and expected build action sets. A stale saved manifest must not bypass revalidation. |
| C15 | Execution versus target platform | Always record worker OS/architecture, tool execution requirements, target TFM/RID/architecture and runtime test host separately. Select native or cross-target acceptance explicitly. A cross-target claim requires execution on the named target runtime plus an unsupported-pair rejection; WebAssembly uses a pinned browser/runtime target. |
| C16 | Graph scale | Use the quantified scale protocol below; retain configured node/edge counts, phase timings, peak memory and action sets. Repository size alone is insufficient. |

Linux x86-64 is the initial general validation lane; retain macOS ARM64 evidence
and add Windows for desktop/Framework cases. OS/architecture lanes are separate
results. Native toolchains, Linux libc variants, workloads and container platforms
need explicit identities; cross-platform artifact sharing is not presumed.

## Replay and handoff protocol

C13 distinguishes preparation-owned inputs from Bazel-generated outputs. A warm
consumer cache does not exercise replay inside its action. Run the following
cases independently and retain evidence of the boundary each reaches.

1. **Preparation-input integrity:** retain a valid input manifest and warm cache,
   then independently remove a declared preparation input or change its bytes
   without updating the recorded digest. Reject the stale manifest before using
   it to publish a replacement plan or request build cache results. Record the
   failing input and validation-stage evidence. An intentional input change with
   a newly validated manifest is a separate successful regeneration control.
2. **Generated-output recovery:** delete Bazel-generated dependency bundles while
   preserving declared preparation inputs. Allow Bazel to materialize outputs from
   cache or rebuild their producers; absence alone is not a stale-manifest error.
   The retained-cache C05 case must prove recovery without producer compilation;
   a separate empty-cache control may rebuild producers in their own actions.
   Consumers must never compile those dependencies internally.
3. **Materialized-bundle integrity:** force consumer execution, then supply a
   bundle with missing artifacts or bytes that disagree with its recorded digest
   at the adapter consumption boundary. Require an integrity rejection before
   replay or consumer compilation. Use a controlled test producer/harness so the
   invalid bundle actually reaches the adapter; do not rely on modifying Bazel's
   internal cache or on the bundle being read during a consumer cache hit.
4. **Replay during consumer execution:** preserve valid producer outputs, then
   force a consumer cache miss using a declared consumer-only change whose new
   action identity has not been cached. Inject a missing required target, invalid
   required metadata or incompatible replay properties at the replay boundary,
   using a test harness that satisfies transport and bundle integrity. Require
   semantic rejection, a consumer/replay execution marker and no dependency
   compilation. Pair every negative case with successful replay of valid results.
5. **Valid producer-result change:** legitimately change producer metadata or
   artifacts and regenerate the result and its digest. Under the initial
   conservative policy, changing consumed bundle bytes must change the consumer
   action identity. Require execution when the test establishes that the new
   identity is absent from every enabled cache; otherwise a valid hit is allowed.
   Compare consumer results with the changed ordinary MSBuild baseline. A valid
   change is not an integrity failure. Later metadata exclusions or
   unchanged-output pruning need their own C04 evidence.

Retain input/result digests, consumer action identities, enabled cache state,
producer recovery/rebuild evidence, validation and replay logs, and execution
markers. Preparation rejection, bundle rejection and replay-semantic rejection
are distinct outcomes; none substitutes for another. Generated bundles need not
exist before Bazel recovers or builds them.

## Capability gates and project-to-check mapping

A gate is satisfied only for a stated slice by a linked contract, executable tests
and passing findings. These gates are proposed requirements, not implemented
capabilities. Native baseline discovery may proceed before adapter prerequisites.

| Gate | Capability required before promoting dependent adapter coverage |
| --- | --- |
| K01 | Baseline generated graph: package-free Release/net10.0, standard outputs, one native platform and conservative dependency bundles. Require C01–C06, C08, C12–C14; C07 checks concurrent builds of this same configuration plus rejection of unsupported globals, and C09 checks the declared baseline environment/path policy. C15 records the native pair. This gate does not require adding TFM/RID/configuration support. |
| K02 | Restore/package closure in generated graphs. Select the F04 features actually used, plus package upgrade/stale-state controls. |
| K03 | Additional configured-node support. Name the requested slice: framework selection/outer-inner builds, Debug/Release, RID selection or architecture; apply C07/C15 to that slice. |
| K04 | Generator/analyzer delivery and behavior. Select G01 or G02 after pinning the generator API; G03 or G04 for generated behavior; and G05, G06 or G10 for delivery. Apply G07–G09 where relevant. G11 is a separate diagnostic-analyzer slice. No project requires every variant. |
| K05 | Custom MSBuild behavior. Select resources (F07), tasks/target ordering (F09), or version/signing inputs (F10) individually. |
| K06 | Distribution operation. Select Pack (F05) or a named Publish mode (F06/P08/P09); define operation identity and output/handoff contract. Publish does not require Pack support. |
| K07 | Native support. Select prebuilt runtime assets, native source compilation/linking, or AOT tools/runtime packs; declare execution/target pair under C15. Loading a prebuilt native asset does not require source-native compilation support. |
| K08 | Frontend or external-tool build. Name the tool and asset/code-generation pipeline; define inputs, outputs, invalidation and recovered-asset oracle. F08 applies to external code generation. |
| K09 | Windows toolchain. Select modern .NET desktop or .NET Framework and name required targeting packs, build tools and runtime/UI test host. Neither lane requires the other. |
| K10 | Composition. Define the selected language build edges, generated-contract edges and runtime relationships; integrate existing Bazel Python/TypeScript rules with the .NET adapter through a shared harness, then prove artifact-only launch. |

Checks apply by operation as follows. “Required” means within the explicitly
supported slice, including rejection of unsupported variants; it does not require
implementing every variant listed in a check. Record exclusions before execution.

| Operation | Required checks and interpretation |
| --- | --- |
| Prepare | C06/C14 discovery and plan regeneration; C03 restore/tool/input mutations, C08 stale/corrupt input rejection, C09 ambient discovery inputs and C15 tool/target identity. Record its phase costs under C12. |
| Build | C01–C09, C12–C15 within the selected configuration/input contract. C13 exercises MSBuild dependency replay; C04 starts with conservative dependent rebuilds. |
| Publish / Pack | C01–C03, C05–C09, C12/C15 for this operation's inputs and artifacts. C04/C13 apply where it consumes dependency results or claims selective reuse; test artifact handoff even when no MSBuild result replay occurs. C14 applies if it performs additional discovery. |
| Test | C01 behavioral oracle on fresh-built and C05-recovered artifacts; C08 missing runtime/test-data controls and C09/C15 declared environment/runtime. Execute tests uncached with no implicit build/restore. Record test time separately under C12; do not claim test-result cache coverage. |
| Launch | C01 runtime oracle using C05-recovered Build or Publish artifacts; C08 missing-artifact/service failure controls and C09/C15 runtime configuration. Start fresh services without implicit build/restore; no launch cache-hit or replay requirement. |
| Design-time | F11 target/output comparison with separate globals and targets; C09/C15 environment, C14 discovery changes and C08 missing-input failures. Actual IDE verification is a separate Windows lane. |
| Clean / Rebuild | F15 operation contract plus C05/C06/C07/C08 output recovery, stale-output removal, configuration isolation and failure controls. Record actual compiler execution separately from cache recovery under C12. |

C10/C11 are separate remote promotions for eligible operations; C16 is a separate
scale qualification. The [remote selections](coverage-project-selections.md#independent-remote-workers-c10c11)
assign bazel-remote to C10 and Buildbarn to C11, initially using the existing
diamond and later P01. All operations record C15 identities, with native or
cross-target acceptance chosen explicitly. Build cache recovery never substitutes
for fresh Test/Launch execution. For non-MSBuild language actions in P07, test the
existing rule set's declared artifact/runfiles handoff; MSBuild result replay applies only
to .NET actions.

The table names the required capability slices and scenario checks for the first
adapter experiment. API classification, exact entry point and feature inventory
must be resolved at pinning; an unlisted upstream requirement becomes an explicit
prerequisite before implementation, not an implicit waiver. Configuration support
is widened only when the selected entry point requires it.

| Project | Required capability slices | Operations | Additional checks / fixture mapping | Initial execution and runtime lane | Adapter status |
| --- | --- | --- | --- | --- | --- |
| P01 Serilog | K01; K02 packages; K03 framework selection; K04 package generator and diagnostics; K05 resources/imports/signing | Build, Test | G05/G07–G09/G11; F07/F09/F10 | Linux x86-64; ordinary baseline on macOS ARM64 | Proposed; ordinary baseline linked above |
| P02 Spectre.Console | K01; K02 packages; K03 framework selection; K04 project generator; K05 resources/imports | Build, Test | G06–G09; pin G01/G02 classification | Linux x86-64 | Proposed |
| P03 EF Core | K01; K02 packages; K03 selected frameworks; K04 resolved analyzers; K05 imports | Build, Test | F04, C16; add K07 runtime assets/F03 only for SQLite extension | Linux x86-64 | Proposed |
| P04 Orchard Core | K01; K02 packages; K03 selected frameworks; K04 resolved Razor/compiler tooling; K05 resources/targets; K06 selected web Publish; K08 frontend assets | Build, Publish, Launch | F07/F09; HTTP/module/static-asset oracle | Linux x86-64 plus pinned frontend tools | Proposed |
| P05 Avalonia | K01; K02 packages; K03 selected frameworks; K05 XAML tasks/resources; K06 Pack for package slice | Separate Build/Test headless and source-task slices; Pack plus consumer Build/Test package slice; later Launch | F05/F07/F09; declare task-host/dependency closure; K07 runtime assets for rendering extension | Linux x86-64 where selected slice permits; Windows/macOS separately | Proposed; pinned source inspection |
| P06 Azure SDK | K01; K02 selected restore features; K03 selected frameworks; K04 resolved analyzers; K05 shared sources/imports | Build, Test | F04/F07, C16; mock tests before isolated playback | Linux x86-64 | Proposed |
| P07 Aspire | K01; K02 selected .NET packages; K03 selected .NET frameworks; K08 existing-rule TypeScript asset integration; K10 multi-language harness and Aspire composition | Build, Launch, Test | F08 where schema generation exists; independent language/shared-schema edits; K06 only if publishing | Linux x86-64 with declared container/runtime resources | Proposed |
| P08 ConsoleAppFramework | K01; K02 packages; K03 selected framework/RID; K04 project generator; K06 Native AOT Publish; K07 AOT compiler/linker/runtime packs | Build, Publish, Test | G06/G09, F06; execute recovered published native test binary without .NET runtime | Linux x86-64 -> linux-x64 | Proposed |
| P09 MudBlazor | K01; K02 packages; K03 framework selection; K04 resolved generators/analyzers; K05 Razor/resources; K06 WASM Publish; K08 frontend assets | Build, Publish, Launch, Test | F07/F08; C15 browser target; add K07 WASM AOT tool/workload closure separately | Linux x86-64 worker and pinned browser, WASM target | Proposed |
| P10 Modern WPF | K01; K02 packages; K03 selected Windows framework; K05 XAML/resources; K09 modern desktop | Build, Launch, Test | F07/F09; XAML/BAML and UI smoke oracle | Windows x64, net10.0-windows | Proposed |
| P11 Framework WPF | K01; K02 packages; K03 Framework selection; K05 XAML/resources; K09 Framework desktop | Build, Launch, Test | F07/F09; Framework targeting/runtime assets | Windows x64, net462 | Proposed |
| P12 Modern WinForms | K01; K02 packages; K03 selected Windows framework; K05 resources; K09 modern desktop | Build, Launch, Test | F07/F09; resources and UI smoke oracle | Windows x64, net10.0-windows | Proposed |
| P13 Framework WinForms | K01; K02 packages; K03 Framework selection; K05 resources; K09 Framework desktop | Build, Launch, Test | F07/F09; Framework targeting/runtime assets | Windows x64, net48 | Proposed |
| P14 Dapper.AOT | K01; K02 packages; K04 package-delivered interceptor generator | Build, Test | G04/G05/G07–G09; valid interception and location mutations | Linux x86-64 | Proposed |
| P15 dotnet/runtime | K01; K02 selected restore; K03 subtree globals; K04 resolved analyzers/generators; K05 bootstrap/imports/versioning | Build, Test; later Publish | C16, F09/F10; add K06/K07 only for selected publish/native extension | Linux x86-64 | Proposed |
| P16 CommunityToolkit.Mvvm | K01; K02 conditional packages; K03 framework selection; K04 project generators/analyzers; K05 shared imports; K06 Pack only for package extension | Build, Test; later Pack and independent consumer Build/Test | G06–G09/G11, F04; C07/C13 reference roles and configured edges; F05 extension | Windows x64 for net472/net8 comparison; net8 slice separately on Linux | Proposed; pinned source inspection |
| P17 Nerdbank.GitVersioning | K01; K02 packages; K03 task/consumer frameworks; K05 source tasks/Git version inputs; K07 native assets as resolved | Build, selected Test; later Pack | F09/F10, C13; build-order nbgv output staging; bootstrap/LKG inventory required | Linux x86-64 net10 consumer/net8 task initially; Framework lane later | Proposed; later pilot, pinned source inspection |
| P18 Server-side Blazor | K01; K02 packages; K03 net10 configuration; K04 resolved Razor tooling; K05 resources; K06 web Publish | Build, Publish, Launch, Test | C01/C05 browser-driven server-circuit oracle; runtime config C09/C15; distinct from P09 | Linux x86-64 server and pinned browser | Proposed; pinned source inspection |

The table selects capability requirements, not an implementation strategy for
Razor or other SDK tooling; inventory its actual resolved tasks/generators when
pinning. F01/F02/F11/F13–F15 now have selected upstream fixtures in the
[selection record](coverage-project-selections.md#remaining-selections-and-coverage-assignments).
These remain separately qualified slices; mobile F12 is still deferred. F05 is
assigned to the P05 package slice, with a distinct P16 analyzer-package extension.
The [MSBuild configured-edge fixtures](coverage-project-selections.md#msbuild-configured-edge-fixtures)
provide focused C07/C13 tests independently of the application portfolio. Add only
the required slice when new upstream behavior is discovered; preserve that
behavior rather than disabling it to avoid a prerequisite.

## Scale protocol

C16 starts with generated **10, 100 and 1,000 configured-node** graphs, each in a
chain and a layered fan-out/fan-in topology with shared dependencies. Pin graph
construction, source sizes, toolchains and worker resources. Then run P03/P06/P15
slices at their actual recorded node/edge counts; a repository with many projects
may still expose only a small selected configured graph.

For each topology/size, compare ordinary MSBuild with the adapter using identical
sources, configured graph, toolchain, worker limits and output oracle. Give each
its own workspace and outputs. Acquire SDK/packages before timing and keep their
warm state matched; report acquisition separately. Use these distinct cases:

| Case | Ordinary MSBuild state | Adapter state |
| --- | --- | --- |
| Fresh execution | Fresh outputs and no replay/result cache | Fresh outputs/output base, empty action/disk caches and remote caching disabled; verify every expected Build action executes |
| Warm no-op | Retain the baseline outputs | Retain baseline outputs/output base and cache; verify zero compilation actions |
| Leaf edit | Independently warm the unmodified baseline, then apply the leaf mutation | Independently warm the same baseline, then apply the identical mutation |
| Shared edit | Independently warm the unmodified baseline, then apply the shared mutation | Independently warm the same baseline, then apply the identical mutation |
| Cache recovery | Delete outputs and rebuild normally; label as an output-deleted rebuild, not a cache-hit comparison | Delete outputs/output base, retain only declared inputs/toolchain and the designated disk cache; require cache hits and execute recovered output |

Mutations must change the intended observable outputs. Predeclare expected work
separately for each build system: Bazel action executions/cache hits under the
adapter's conservative policy, and ordinary MSBuild project/target execution and
actual compiler invocations under its incremental behavior. Project or target
visits alone do not prove compilation. Retain Bazel execution logs and MSBuild
binary logs with compiler-execution evidence.

Both systems must match the same observable-result oracle; they need not perform
the same work. Report different valid execution sets as efficiency differences.
A deviation from a system's own predeclared expectation fails that check and
requires investigation; it is not automatically a semantic correctness failure.
No mutation may inherit state from another case. Reinitialize the specified state
before every measured repetition; a setup/warm-up run must not populate a
fresh-execution case's build cache.

Run at least five measured repetitions **per case, topology, size and build
system**, interleaving system order to reduce drift. Measure ordinary MSBuild's
end-to-end time and corresponding evaluation/build phases where observable;
measure adapter preparation/export, Bazel analysis, execution and end-to-end wall
time. Record phase attribution rather than treating unlike phases as equivalent.
Report median and range, compiler/action counts and complete output oracles.

Peak memory is the peak aggregate resident memory of the invocation's process
tree, including descendant build/compiler/tool processes. Use dedicated workers
or account explicitly for persistent compiler/build servers; record measurement
tool, sampling interval and whether server reuse is enabled. A parent process's
maximum RSS alone cannot satisfy this metric. Keep server policy consistent
across repetitions and disclose differences between systems.

At each size, report observable correctness and work-set acceptance separately.
Require the shared output oracle and each system's own expected work set; never
require identical work sets across systems. No-op qualification requires zero
actual compiler invocations in both systems, even if project/target evaluation
still runs. Timeouts and memory exhaustion count as failed scale levels, not
skipped results. Before a performance qualification
run, record numeric end-to-end no-op latency and peak-memory budgets for each size
on the chosen worker. Budgets remain **unset** until baseline calibration; report
measurements without a performance-pass claim while unset, and never select a
threshold after viewing the qualification results. Report cache-recovery benefits
separately from fresh-execution and incremental-build comparisons.

## Sequencing and completion records

1. Finish K01, including explicit C13 replay and C14 discovery controls; integrate
   K02 package cases into the generated graph. Retain existing rejection tests.
2. Establish the P01-selected K03/K04/K05 slices through small fixtures and the
   Serilog adapter pilot.
   Promote only the selected configuration and operation, then widen coverage.
3. Use upstream MSBuild configured-edge fixtures for C07/C13 controls and P16 for
   combined reference roles/frameworks. Retain P02 for analyzer-project delivery
   with additional data inputs and P14 for interception. Investigate
   P08 Native AOT early, but gate adapter acceptance on K06/K07 rather than its
   position in the project list.
4. Expand independent capability tracks: P03/P06 for graph scale, P04/P09 for web
   assets, P05 for separate source-task and package-consumer experiments, then
   native rendering; P10–P13 for Windows desktop. Keep P17 as the later task/Git
   pilot after the P05 task contract. Start
   C16 synthetic measurements before attributing performance to repository size.
5. Add P07 after K10 composition contracts, and P15 in pinned managed slices before
   native expansion. C10 remote cache and C11 remote execution remain independent
   gates using the selected remote infrastructure; neither requires finishing
   the entire application portfolio first.
6. Add F13/F14 entry-point/SDK controls while expanding preparation; define F15
   Clean/Rebuild ownership before exposing those operations. Run F01/F02 and F11
   in their own language/Windows/IDE lanes. P18 adds server-side Blazor separately
   from P09 WebAssembly; optional mobile and advanced IDE extensions stay deferred.

For each experiment, create a findings record before implementation with these
fields; fill results only after execution:

| Field | Required content |
| --- | --- |
| Identity | Project/scenario IDs, upstream commit, entry point, requested operation/targets, global properties and toolchain/package pins. |
| Prerequisites | Applicable K gates and linked passing slices; explicit exclusions and their effect on the claim. |
| Platform | Execution OS/architecture, target framework/RID/architecture, and runtime test host. |
| Coverage | One row per required C/G/F check: test ID, proposed/contract-only/measured status, command, expected result, observed result and evidence link. Split stages when only some have passed. |
| Operation contract | Inputs, discovery triggers, output/replay schema, cache eligibility and allowed preparation/network behavior. |
| Results | Baseline/adapter oracle, expected/observed action sets, artifact comparison, logs and remaining failures. |
| Performance | Graph size/topology, worker resources, cache state, repetitions, phase timings, memory and predeclared budgets when claiming performance acceptance. |

A slice is complete only when its applicable prerequisites and required checks
have passing evidence on its named platform. Keep unsupported extensions and
other platforms proposed; never replace the entire project status with “covered”
because one build succeeded.
