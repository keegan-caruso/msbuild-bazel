# Time dependencies in the testing portfolio

Source audit: 2026-09-08 UTC, adapter baseline `fd455b9`. This covers all P01–P18 entries in the [testing portfolio](scenario-coverage.md), the supplemental build/IDE fixtures and remote infrastructure in [project selections](coverage-project-selections.md), and the later ASP.NET Core sample alternative.

**Finding:** several real portfolio projects use clock values in build evaluation or generated artifacts. File modification times also participate in build-tool caches and incremental decisions. These are distinct contracts: normalizing file timestamps cannot remove a direct `DateTime.Now` read. The resulting [support contract](deterministic-ci-contract.md) targets deterministic CI builds with qualified, explicit time inputs.

This is static source and call-site inspection, not a new ordinary/adapter execution result. Existing plan revisions were retained; unpinned candidates were frozen at the default-branch commit observed during this audit. The [source inventory](project-time-audit-sources.json) records exact commits and scan scope. Different framework lanes sharing a repository were inspected at the same source revision.

## Portfolio results

“None found” below means no direct time-dependent build/generator expression identified in the inspected source; it is not certification of all transitive task/compiler/native dependencies. Runtime clocks, test timeouts, logging and benchmark timers do not by themselves make compiled artifacts time-dependent.

| ID | Project | Build-time finding and selected-slice relevance |
| --- | --- | --- |
| P01 | Serilog | None found in checked-in build files or compiler-generation inputs. Library/runtime tests use dates; the selected approval build is not shown to depend on wall time. |
| P02 | Spectre.Console | None found in checked-in build files or the shared source generator. MinVer/SourceLink require declared Git state; that requirement is distinct from the timestamp-only R09 fixture. External tool closure still needs qualification. |
| P03 | EF Core | **Conditional shared-tooling dependency.** The pinned Arcade import uses the current UTC date for official/shipping versions when no explicit build ID/timestamp is supplied. Ordinary dev settings do not activate that branch. MigrationsIdGenerator also reads UTC time, but it generates migration IDs when the tool is invoked, not during the selected library compilation. |
| P04 | Orchard Core | **Generated frontend artifacts.** TheAgencyTheme, TheBlogTheme and TheComingSoonTheme asset scripts insert the current year into generated JS/CSS copyright headers. Relevant when the selected theme asset build executes; a host using already-generated checked-in assets is a different case. |
| P05 | Avalonia | **Direct evaluation/output metadata.** SharedVersion.props derives copyright from the current year and is imported by src projects and selected XAML/headless tests. Separately, the XAML task sets copied output mtimes to UTC now to support incremental checks. |
| P06 | Azure SDK | **Direct development-version dependency.** Versioning.targets defaults its build number to today's local date when OfficialBuildId is absent and appends it to Version unless SkipDevBuildNumber is true. Shared core/storage build imports reach this policy. |
| P07 | Aspire polyglot task queue | None found in the selected sample's checked-in build/generator code. Service/browser clocks and lifecycle timeouts belong to Launch/Test. Container publishing has a separate SDK metadata contract; see below. |
| P08 | ConsoleAppFramework | None found in the actual source generator or NativeAotTests build declarations. Clock reads in GeneratorSandbox/Filters are executed command logging, not generator execution. AOT toolchain/native closure remains a separate qualification. |
| P09 | MudBlazor | **Conditional source-regeneration output.** Update-MudIcons.ps1 embeds the current date/time in generated C# comments. No direct build-time clock read identified when compiling the checked-in icons. WebAssembly SDK timestamp behavior also needs qualification for the browser lane. |
| P10/P11 | MaterialDesignInXamlToolkit, modern and Framework WPF | **Packaging wrapper.** BuildNugets.ps1 supplies the current year as Copyright to dotnet pack --no-build. That demonstrates time-dependent package metadata through this wrapper, not a clock read in the selected ordinary WPF compile. Windows SDK/XAML tasks need separate qualification. |
| P12/P13 | Krypton Standard Toolkit, modern and Framework WinForms | **Direct evaluation and assembly/package versions.** Shared targets compute year, month and day-of-year and use them in LibraryVersion, PackageVersion, AssemblyVersion and FileVersion, including the default configuration branch. One Docking project additionally puts UTC wall time in SourceRevisionId. |
| P14 | Dapper.AOT | None found in the inspected compiler generator/build code. Git-derived versioning and source-location identity remain separate inputs. |
| P15 | dotnet/runtime | **Conditional clock and actual file-metadata dependency.** Arcade has the official/shipping date fallback. The corelib crossgen/PGO target hashes optimization-file ModifiedTime into its merge-input cache. WebAssembly targets also write input mtimes into conversion stamps. These belong to their runtime/SDK extensions, not automatically to every selected managed library. |
| P16 | CommunityToolkit.Mvvm | None found in inspected build files or generator implementation. Time-dependent unit/runtime logic is not evidence that the selected Roslyn generator emits different code with time. |
| P17 | Nerdbank.GitVersioning | **Conditional native-resource output.** NativeVersionInfo supplies the current year when AssemblyCopyright is absent, in the C++ resource path. This does not establish clock dependence in the selected managed Tasks/library consumer. ReleaseManager uses current time for newly authored Git commit signatures, a separate release operation. |
| P18 | Server-side Blazor sample | None found in the selected project's checked-in build files. Weather/date examples execute at runtime. HTTPS certificate creation and browser/service lifetime checks need explicit Launch/Test treatment. |

## Concrete source evidence

### Krypton: current date becomes version identity

[Shared component targets, lines 99–124](https://github.com/Krypton-Suite/Standard-Toolkit/blob/59f791271f7f682841461fcde167b39ba75e6dd2/Source/Krypton%20Components/Directory.Build.targets#L99) use the current year/month/day in the default branch as well as Canary/Nightly/Installer. The values flow into assembly, file and package versions. This affects both planned framework lanes.

[Krypton.Docking 2022.csproj, line 45](https://github.com/Krypton-Suite/Standard-Toolkit/blob/59f791271f7f682841461fcde167b39ba75e6dd2/Source/Krypton%20Components/Krypton.Docking/Krypton.Docking%202022.csproj#L45) sets SourceRevisionId from UTC time down to milliseconds. Inventory the final selected entry point and overrides before claiming that this additional per-build value affects every toolkit consumer.

### Avalonia: year in metadata, current mtime in a task

[SharedVersion.props, line 7](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/build/SharedVersion.props#L7) computes the year. [src/Directory.Build.props](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/src/Directory.Build.props#L3) and the [selected XAML test project](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/tests/Avalonia.Markup.Xaml.UnitTests/Avalonia.Markup.Xaml.UnitTests.csproj#L10) import it.

[CompileAvaloniaXamlTask.CopyAndTouch](https://github.com/AvaloniaUI/Avalonia/blob/b709c58c6b1b8aa3b90866c7c001b7bf82b6353b/src/Avalonia.Build.Tasks/CompileAvaloniaXamlTask.cs#L35) copies and touches outputs when compilation succeeds without writing a new file. Its stated purpose is incremental build checking. This is different from embedding the clock in assembly bytes.

### Azure SDK: explicit build ID or today's date

[eng/Versioning.targets, lines 3–16](https://github.com/Azure/azure-sdk-for-net/blob/eab6b95ea4438b8e9b9c80c3f574e506ba1c1337/eng/Versioning.targets#L3) reads the current date only if OfficialBuildId is absent. The development suffix is conditional on SkipDevBuildNumber. [Directory.Build.Common.targets](https://github.com/Azure/azure-sdk-for-net/blob/eab6b95ea4438b8e9b9c80c3f574e506ba1c1337/eng/Directory.Build.Common.targets#L3) imports the version policy. Supplying an explicit ID is an existing upstream input contract; silently dropping the suffix changes behavior.

### Orchard Core: emitted JS/CSS headers

The [Blog theme JS builder](https://github.com/OrchardCMS/OrchardCore/blob/5b87b3fad1814235465af0614f72d6a36e85dbfb/src/OrchardCore.Themes/TheBlogTheme/Assets/TheBlogTheme/scripts/render-scripts.js#L17) constructs a current-year copyright banner and writes it into the destination file. Its sibling render-scss.js does the same for styles, as do the Agency and ComingSoon themes. The selected host/theme and frontend command must be pinned before turning this into an active acceptance requirement.

### MaterialDesign and MudBlazor: operation-specific generation

[MaterialDesign BuildNugets.ps1](https://github.com/MaterialDesignInXAML/MaterialDesignInXamlToolkit/blob/3f6e67aaee6b5728cab6c45d5ce419cd9b37ab22/build/BuildNugets.ps1#L7) computes a current-year copyright string and passes it to `dotnet pack --no-build` at line 19. Qualify that package operation separately from ordinary compilation.

[MudBlazor Update-MudIcons.ps1](https://github.com/MudBlazor/MudBlazor/blob/6c1a2e986fb8d79c0ec85a03bc7879f1f01d449f/tools/Icons/Update-MudIcons.ps1#L103) writes a current timestamp into regenerated source comments. Compiling existing checked-in icons does not execute this authoring script. If regeneration enters Prepare/Build, declare its timestamp and downloaded icon inputs; a comment still changes generated source bytes and can affect downstream debug/source artifacts.

### dotnet/runtime: file timestamps enter a cache hash

[GenerateMergeMibcFilesInputCache](https://github.com/dotnet/runtime/blob/fb98b574c9c5bcea55f33dbad31c418c8815ce8e/src/coreclr/crossgen-corelib.proj#L82) hashes file paths plus ModifiedTime values, then writes a cache file that drives the PGO merge target. A file touch can therefore change an intermediate artifact without changing optimization-data bytes. This is a concrete repository use of the same metadata category exercised by the synthetic R09 probe.

The [WebAssembly build conversion stamp](https://github.com/dotnet/runtime/blob/fb98b574c9c5bcea55f33dbad31c418c8815ce8e/src/mono/nuget/Microsoft.NET.Sdk.WebAssembly.Pack/build/Microsoft.NET.Sdk.WebAssembly.Browser.targets#L426) writes project, target, task and prebuilt-input mtimes into a file; the publish counterpart does so at line 1069. This identifies an SDK-closure qualification case for the P09 browser lane. It does not establish that the installed SDK contains this particular source revision.

The runtime test environment also derives a JitStress seed from [current milliseconds](https://github.com/dotnet/runtime/blob/fb98b574c9c5bcea55f33dbad31c418c8815ce8e/src/tests/Common/testenvironment.proj#L217). That is test-scenario generation, separate from the selected managed-library Build contract.

### Arcade: conditional, with an upstream deterministic input

EF Core's [dependency manifest](https://github.com/dotnet/efcore/blob/48ebeecf35dc04b90ace28d7a23dfdc7bdc12e88/eng/Version.Details.xml#L63) pins Arcade through the dotnet source repository. At that declared source revision, [Version.BeforeCommonTargets.targets, lines 27–54](https://github.com/dotnet/dotnet/blob/1ec061ee82223a1fff7f84bd78726d18914ebf87/src/arcade/src/Microsoft.DotNet.Arcade.Sdk/tools/Version.BeforeCommonTargets.targets#L27) uses OfficialBuildId, then DeterministicTimestamp/SOURCE_DATE_EPOCH, then UTC today. The enclosing condition requires OfficialBuild or DotNetUseShippingVersions.

The corresponding source revisions declared by runtime, sdk, msbuild and the later aspnetcore candidate were inspected too; they have the same conditional fallback. Those versions and links are recorded in the source inventory. This is source provenance from dependency manifests, not verification of restored package bytes.

### Nerdbank: distinguish native fallback from unused timestamp helper

[NativeVersionInfo.cs, line 230](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/src/Nerdbank.GitVersioning.Tasks/NativeVersionInfo.cs#L230) has the year fallback. The [native target](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/src/Nerdbank.GitVersioning.Tasks/build/Nerdbank.GitVersioning.targets#L210) is separate from managed version-source generation.

The scan also found a timestamp/length helper named FastFileEqualityCheck. Inspection of [CompareFiles.cs](https://github.com/dotnet/Nerdbank.GitVersioning/blob/700f125382c10bb149e52df4fc8513a86886c8ef/src/Nerdbank.GitVersioning.Tasks/CompareFiles.cs#L78) shows the Execute path compares file contents instead; do not count that helper as proof of timestamp-based equality on the active path.

## Supplemental fixtures and infrastructure

| Plan source | Finding and boundary |
| --- | --- |
| MSBuild solution/configuration/resolver fixtures | The engine itself exposes file-time metadata and uses timestamps for target up-to-date checks. Microsoft.Common.CurrentVersion.targets observes assembly timestamps before/after compilation. That does not mean the selected graph fixture embeds today's date. Its repository Arcade build has the conditional shipping-version fallback. |
| MSBuildSdks Traversal/NoTargets/Clean fixtures | No clock-derived output identified in these selected SDK slices. Other SDKs in that repository, notably Artifacts and CopyOnWrite, have filesystem timestamp logic; do not generalize those findings to Traversal. |
| dotnet/sdk Clean/VB fixtures | No direct clock embedding identified in those selected fixture declarations. ResolvePackageAssets compares assets/cache mtimes; broader SDK container publishing can derive tags and image creation metadata from the clock unless configured. This is relevant when extending the plan to container publishing, not proof that a VB compile embeds time. |
| NuGet.Client restore fixtures | Restore cache expiry, signature validity, file timestamps and tests of unchanged restore outputs use time. This belongs to acquisition/restore and its cache protocol; it does not establish a clock-dependent compilation output in the generated legacy fixture. |
| dotnet/project-system design-time/IDE fixtures | IDE up-to-date and design-time compilation decisions depend on file/build timestamps. Preserve those stateful behaviors in F11; a cached normal Build is not a substitute for IDE-state tests. |
| bazel-remote | Service idle/time-based operational behavior and timing tests are present. These are cache-service lifecycle concerns, not source timestamp inputs to a .NET action key. |
| Buildbarn bb-deployments | No direct clock expression found in inspected deployment configuration. This source selection does not include every deployed service/image implementation or prove time-independent service behavior. |
| Later ASP.NET Core mixed-render-mode candidate | Conditional Arcade versioning, development-certificate validity times and lifecycle/tooling clocks. Keep this separate from the smaller P18 blazor-samples project. |

Representative primary sources: [MSBuild incremental contract](https://learn.microsoft.com/en-us/visualstudio/msbuild/incremental-builds?view=visualstudio), [SDK assets cache](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/src/Tasks/Microsoft.NET.Build.Tasks/ResolvePackageAssets.cs#L599), and [SDK container targets](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/src/Containers/packaging/build/Microsoft.NET.Build.Containers.targets#L81). SDK source selection here is the testing-plan pin, not a claim that every line is identical to the currently installed 10.0.400 SDK.

Additional primary sources: SDK [container creation time](https://github.com/dotnet/sdk/blob/fcd632a06320edcb05ac62f20e150da48b00b6a8/src/Containers/Microsoft.NET.Build.Containers/Tasks/CreateNewImage.cs#L184) uses SOURCE_DATE_EPOCH when supplied, otherwise UTC now; NuGet [source cache age](https://github.com/NuGet/NuGet.Client/blob/5fe0c128b2d58335a60161c5141064be42dd8a6b/src/NuGet.Core/NuGet.Protocol/SourceCacheContext.cs#L82) and [signature chain verification time](https://github.com/NuGet/NuGet.Client/blob/5fe0c128b2d58335a60161c5141064be42dd8a6b/src/NuGet.Core/NuGet.Packaging/Signing/Utility/CertificateChainUtility.cs#L93); project-system [build-start tracking](https://github.com/dotnet/project-system/blob/1379b2dce76234664ad1b970e0bd72dc95c75e68/src/Microsoft.VisualStudio.ProjectSystem.Managed.VS/ProjectSystem/VS/UpToDate/UpToDateCheckBuildEventNotifier.cs#L79); bazel-remote [idle service timing](https://github.com/buchgr/bazel-remote/blob/a69b6b5ed933234d93b489ffd216bee5bb74aa06/utils/idle/idle.go#L52).

## Implications for the plan

The accepted support target is **deterministic CI builds**, as defined in the [support contract](deterministic-ci-contract.md). It is an eligibility requirement, not new execution evidence or authorization to resume paused R09 implementation.

1. Add real clock-dependent evaluation controls from **Avalonia, Azure SDK and Krypton** to R09's eligibility contract. Use **Orchard theme generation** for generated asset contents and the **runtime PGO target** for a file-metadata-dependent intermediate when those slices begin.
2. Keep clock values and file timestamps separate. An epoch applied to staged files does not affect DateTime.Now, a generated current-year banner or date-based versioning.
3. Prefer existing upstream explicit inputs where available: Azure OfficialBuildId; Arcade OfficialBuildId or DeterministicTimestamp. Include them in discovery/action identity. Preserve upstream semantics and compare against an ordinary build using the same declared inputs.
4. For direct clock reads without a qualified override, define an explicit supported behavior before enabling reuse. Do not quietly reuse yesterday's version or claim parity after removing an upstream header.
5. Validate incremental behavior in a controlled staged workspace with the appropriate input/output timestamp ordering. Avoid a universal “set every timestamp equal” rule: SDK/tasks can use timestamps to decide whether necessary work runs.
6. Keep a negative R09 probe for equal content keys with different observations. Its scenario is no longer only hypothetical across the portfolio, but the synthetic probe still does not prove a failure in Serilog or Spectre.
7. Apply eligibility to discovery and to any output-producing cached action that reads time. Fresh discovery alone does not repair a compile/package action whose identity omits a meaningful clock input.

## Method, reproduction and limits

The scanner streams each exact-revision public GitHub source archive and searches recognized source, MSBuild, script and configuration text. It retains matches and build-related files for manual inspection; it does not execute upstream scripts or extract arbitrary archive links. This run covered 24 repositories and 258,280 recognized text files, with six recognized files excluded for size. An additional pass checked retained build files for MSBuild/PowerShell static-property syntax and batch clock variables. Matches were reviewed for active conditions, consumers and runtime/test false positives.

Reproduce the broad source scan with:

```sh
python3 tools/audit_project_time.py --output artifacts/time-audit-new
```

The inventory freezes this audit's candidate revisions. Outputs must use a separate evidence location; do not interpret a new default-branch scan as the same evidence. Local evidence for this run is under `artifacts/time-audit/`, with one scan.json per repository and exact source excerpts. Downloaded source and raw scans stay ignored. No application build, restore, native acceptance, clock manipulation, CI dispatch or change to production preparation reuse was performed.

Static matching is not a complete read trace. Dynamically constructed expressions, external package/task/native payloads, submodules, generated files, unrecognized languages and skipped large/binary files can contain additional dependencies. “No direct read found” therefore remains a scoped inspection result. The source inventory records scanned counts and exclusions; compiler/task closure and selected entry-point execution still need acceptance evidence.
