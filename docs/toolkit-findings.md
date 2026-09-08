# CommunityToolkit configured generator graph

The selected CommunityToolkit graph at
`b135626dd54d33b8f05f2ff31591592c004aa848` passes the full selected native macOS ARM64
execution with SDK 10.0.400 and Bazel 8.4.2. The upstream Roslyn4001 test
project targets net10.0; its ordinary SDK negotiation selects both net8.0 and
netstandard2.0 instances of the Mvvm library and netstandard2.0 generators.
All 11 isolated actions compile only their own project. The 69 selected upstream
ObservableProperty and RelayCommand tests pass from staged outputs, matching
ordinary MSBuild. Preparation sources are deleted before Bazel execution.

## Contract changes

Framework selections identify configured project instances, retaining both
frameworks of the same project and each owner's selected dependency framework.
The net8.0 reference pack is the exact SDK restore download
Microsoft.NETCore.App.Ref 8.0.30, verified against the package policy and declared
as an action input. Other net8 reference pack versions remain unsupported.

Restore validation compares configured project snapshots. It accepts the
upstream analyzer reference privacy (`contentfiles;build`) and PolySharp's
`build;analyzers` asset selection, while validating the restored selection.
Exact package archive/content hashes cover the selected restored closure.
NuGet's escaped plus sign in portable framework archive names is decoded before
path validation and extracted-payload comparison.

Copied embedded source templates are content inputs in dependency staging.
Replay retains successful helper target results (including GetTargetPath),
requires every explicitly requested result, and excludes unrequested skipped
initial hooks. InitializeSourceRootMappedPaths participates in the target
contract. Canonical HTTP(S) metadata remains opaque metadata. Compilation uses
the in-action compiler instead of a process shared outside the action.

The only baseline integration overlay declares upstream version.json through
BazelExtraInput. Upstream signing, generator/reference declarations, package
versions, framework negotiation, default Nerdbank auxiliary caching and
SourceLink remain enabled. Restore enables Windows targeting to acquire the
upstream all-framework snapshots; execution selects the graph described above.

## Reproduction and evidence

Use a full Git clone of https://github.com/CommunityToolkit/dotnet at the pin
above with its restored `.nuget/packages` cache. Restore the selected upstream
project with `-p:EnableWindowsTargeting=true`; do not force a global framework
during restore. Then run in the pinned environment:

```sh
python3 tools/probe_toolkit_acceptance.py \
  --source /path/to/restored/CommunityToolkit \
  --output /tmp/toolkit-acceptance
```

Full evidence: `/private/tmp/r05-toolkit-full-2/report.json` (`accepted`).
Every positive run matches all 69 upstream tests and the ordinary runtime DLL set.

| Case | Executed actions | Result |
| --- | ---: | --- |
| Cold | 11 | Each action compiles only its own project |
| Unchanged | 0 | No rebuild |
| Shared generator implementation | 10 | Generator owners and descendants rebuild; net8 library remains cached |
| Conditional Bcl.AsyncInterfaces 10.0.1 to 10.0.11 | 4 | Both library instances, external assembly and tests rebuild |
| Supporting PolySharp 1.15.0 to 1.16.0 | 11 | Shared import/package change reaches all configured nodes |
| Relocated baseline | 0 | 11 explicit disk-cache hits, identical bundle bytes/modes |
| Relocated consumer edit | 1 | Only the test project compiles, then all 69 tests pass |

The package conditional remains netstandard2.0-only; both library instances
invalidate because their shared project-file bytes changed. This is conservative
project-input identity, not an ABI optimization. Generator API inspection confirms
ObservablePropertyGenerator and RelayCommandGenerator implement IIncrementalGenerator.
Analyzer edges retain OutputItemType=Analyzer, ReferenceOutputAssembly=false and
contentfiles;build privacy. Packaging/build-order edges remain scheduling edges;
ordinary codefixer-to-generator references retain their normal compiler role.

The first full attempt was invalidated by committing while the run was active:
rebuilt tool assemblies included a different Git revision. Its unexpected extra
work was correctly attributable to changed tool bytes, not the package mutation.
The passing rerun kept tool inputs fixed. A native diamond regression exposed
SDK-added transitive references; unique framework selections now apply to those
references, with explicit owner selections taking precedence. The focused native
rerun passes. Across the graph regression suite and that fix rerun, 38 tests pass
and one acquired-Serilog fixture prerequisite is skipped. Owned .NET style/build
checks and all five style enforcement controls pass.

This is selected Build/Test evidence. Windows/net472 comparison, Linux,
CommunityToolkit Pack, all test projects and other framework combinations remain
separate. It does not establish remote execution or complete host closure.
