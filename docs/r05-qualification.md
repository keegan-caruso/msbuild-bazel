# R05 qualification and remaining combinations

R05's selected native macOS ARM64 scope combines the accepted synthetic
API/delivery fixtures, Spectre.Console, CommunityToolkit.Mvvm and Dapper.AOT.
The platform decision is recorded in [active validation scope](platform-validation-scope.md).
The selected gates retain MSBuild compilation, package semantics and native
sandbox actions. They do not establish universal generator compatibility.

## Evidence by selected slice

| Slice | Evidence and boundary |
| --- | --- |
| Synthetic classic/incremental generators and diagnostic-only analyzers | [R05a](r05a-findings.md): independent project/package delivery, input mutations, failed diagnostics, runtime/reference roles, recovery and fresh recovered consumer |
| Spectre.Console P02 | [Acceptance](spectre-acceptance-findings.md): pinned project generator, additional JSON/configuration changes and removals, supporting packages, Git/SourceLink and producer-free recovery |
| Shared Nerdbank | [Explicit mode](shared-versioning-findings.md) and [default auxiliary caching](default-versioning-findings.md): source/version/Git inputs, both SourceLink versions, build-ID invalidation and rejection controls |
| CommunityToolkit P16 | [Acceptance](toolkit-findings.md): seven cases over 11 configured nodes; all 69 selected upstream tests pass ordinarily, cold, after mutations and after recovery |
| Dapper.AOT P14 | [Acceptance](interceptor-findings.md): 11 cases prove interception, source-location invalidation, compiler-feature failure and relocated recovery/fresh execution |

All newly executed acceptance uses SDK 10.0.400, Bazel 8.4.2, Release and native
macOS ARM64. Earlier reports retain their original SDK/platform pins. GitHub CI
has not been dispatched for this work.

## G01–G11 disposition

| Cell | Qualified slice or explicit deferral |
| --- | --- |
| G01 classic API | R05a ISourceGenerator fixture: cold, changed/removed input and recovered execution |
| G02 incremental API | R05a fixture plus Toolkit ObservableProperty/RelayCommand and Dapper's IIncrementalGenerator implementation at inspected pins |
| G03 ordinary generated API | R05a and Toolkit prove generated APIs execute. The specifically proposed System.Text.Json no-reflection serializer oracle is deferred; those APIs do not substitute for that serializer proof |
| G04 interceptors | Dapper runtime positive/negative oracle, path/line mutations, call changes/removal and producer-free recovery |
| G05 package delivery | R05a mixed package generators/analyzers, existing PolySharp qualification, Toolkit PolySharp upgrade and Dapper analyzer/support closure |
| G06 project delivery | R05a, Spectre and Toolkit retain ordinary/analyzer/build-order distinctions; ConsoleAppFramework and its Native AOT combinations are deferred |
| G07 non-source inputs | R05a AdditionalFiles, editor options and compiler-visible properties; Spectre JSON/configuration; shared version.json/Git and consumer-supplied inputs |
| G08 lifecycle/diagnostics | Removed inputs and generator failures in R05a/Spectre; removed interception bindings in Dapper; diagnostic severity/suppression/error controls in R05a |
| G09 compatibility | SDK/compiler inputs and exact feature settings are declared; Dapper namespace opt-out and C#11 fail explicitly. Arbitrary compiler-version cross-products are deferred |
| G10 SDK/framework generators | SDK/reference-pack bytes are action inputs, but a behavioral serializer oracle plus an actual SDK/pack upgrade matrix is deferred. Mere compiler loading is not counted as qualification |
| G11 diagnostic-only analyzers | R05a project and package analyzer versions, severity, suppression and warnings-as-errors, including failed-build nonpublication and recovered consumer execution |

The deferred combinations are explicit remaining coverage, not hidden milestone
prerequisites: R05's exit permits a passing selected slice or a recorded deferral
for every cell. Windows net472/net8 and Linux Toolkit comparisons, additional
upstream test projects, R06 analyzer packaging/Pack, Native AOT, remote workers,
complete host closure and cross-platform reuse remain separate. ABI-sensitive
compile avoidance and runtime-sensitive retesting remain R09 follow-up contracts.

## Integration validation

CommunityToolkit: `/private/tmp/r05-toolkit-full-2/report.json`, seven cases accepted.
Dapper: `/private/tmp/r05-interceptors-final/report.json`, 11 cases accepted.
Graph regressions: 38 pass across the native suite and focused transitive-framework
fix rerun, with one existing acquired-Serilog fixture prerequisite skipped.
Package regressions: 22 pass, two existing acquired-Serilog prerequisites skipped.
Direct action-runner contract/process tests, scaffold/Starlark validation and owned
.NET builds/style checks pass. Both final combined generator/diagnostic matrices pass all 10 cases each:
`/private/tmp/r05-final-combinations-project/report.json` and
`/private/tmp/r05-final-combinations-package/report.json`. These rerun project and
package analyzer upgrades, suppression, severity, warnings-as-errors, failure
nonpublication, relocated cache recovery and fresh recovered consumer compilation
on the combined implementation. The full Toolkit and Dapper matrices remain the
track evidence above; they are not represented as rerun after documentation-only
integration commits.
