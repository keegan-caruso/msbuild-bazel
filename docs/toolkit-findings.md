# CommunityToolkit configured generator graph

The selected CommunityToolkit graph at
`b135626dd54d33b8f05f2ff31591592c004aa848` passes cold native macOS ARM64
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
  --output /tmp/toolkit-acceptance --cold-only
```

Cold evidence: `/private/tmp/r05-toolkit-evidence-8/report.json` (`coldAccepted`).
The full harness also runs unchanged, shared-generator, conditional-package,
supporting-package, relocated recovery and consumer mutations; acceptance is
reported only when every case completes. That matrix is pending at this
checkpoint. Owned .NET style/build checks pass; configured framework unit tests
cover duplicate project paths with distinct selected frameworks.

This is selected Build/Test evidence. Windows/net472 comparison, Linux,
CommunityToolkit Pack, all test projects and other framework combinations remain
separate. It does not establish remote execution or complete host closure.
