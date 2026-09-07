# SDK-selected reference frameworks

The unchanged Serilog approval test project targets net10.0 and references the
multi-targeted Serilog library. Ordinary MSBuild selects the compatible net10.0
inner build. The pinned static graph instead expanded every framework, which
exceeded this adapter's supported Release/net10.0 scope.

Discovery now runs the pinned SDK's `PrepareProjectReferences` on a disposable
project instance, copies its negotiated `SetTargetFramework` metadata, and clears
`InnerBuildProperty` and `InnerBuildPropertyValues` on selected C# graph instances.
Outer builds and traversal instances retain their original interpretation. Source
project declarations and configured global properties remain unchanged. Unsupported
selected frameworks and ambiguous reference paths still fail closed.

Both graph markers must be cleared: the pinned MSBuild graph interpretation
removes the inner-build global property after merging reference metadata, otherwise
undoing the SDK's selection. See the [pinned implementation](https://raw.githubusercontent.com/dotnet/dotnet/b0f34d51fccc69fd334253924abd8d6853fad7aa/src/msbuild/src/Build/Graph/ProjectInterpretation.cs).
The graph execution record also carries the exact selected reference paths and
frameworks so execution can reproduce the declared selection.

Measured on macOS ARM64 with SDK 10.0.100:

```
python3 -m unittest discover -s tests/graph -v
```

All 20 tests passed, including configured Flavor variants and a diamond whose
shared dependency declares net10.0 and netstandard2.1. The latter exports four
net10.0 nodes without changing the declaration or producing compiled DLLs.
An unsupported SDK-selected framework remains rejected. The two new tests passed
again after adding the selected-reference execution metadata.

This discovery evidence does not yet establish action execution of that graph.
The action-side import must reproduce selection before a native acceptance run.
Linux validation is deferred.

## Native action adaptation

Preparation carries each node's exact `execution.selectedReferences` into a
declared action request, together with the selected project/framework closure.
It rejects selected edges that disagree with graph dependencies and conflicting
same-path framework selections. The runtime produces a request-derived import
appended through `AfterMicrosoftNETSdkTargets`, after the SDK assigns its static
graph markers. For declared net10.0 projects it clears both graph markers without
changing `TargetFrameworks`, then attaches the SDK-selected SetTargetFramework to
existing authored references. No global identity property is added or ignored.

The SDK can add transitive references from restore after evaluation. Before its
framework negotiation target, the import also decorates existing transitive items
with the same exact selected framework from the declared closure. This remains
bounded to net10.0 callers and dependencies and retains their graph edges. The
first native diamond exposed MSB4252 when App's transitive Shared reference asked
for an unconfigured GetTargetFrameworks result; the late target closes that gap
without disabling transitive references or isolation.

A fresh native macOS diamond with Shared declaring `net10.0;netstandard2.1` passes
at `/private/tmp/selected-framework-native-3`. Ordinary SDK Build and four native
sandbox project actions return `shared-v1:left|shared-v1:right`. App replays Shared,
Left and Right after the preparation workspace is deleted; every action compiles
only its own project. The original multi-target declaration remains in the staged
project. This is cold execution evidence, not cache recovery or Linux qualification.
The three selection preparation tests, seventeen existing preparation tests and
runner contract/process tests also pass.

```sh
python3 tools/probe_graph_execution.py --selected-reference --output /private/tmp/selected-framework-native-3
python3 -m unittest discover -s tests/graph_execution -p test_framework_selection.py -v
python3 -m unittest discover -s tests/graph_execution -p test_prepare_graph.py -v
bash scripts/dotnet.sh run --project tests/ActionRunner.Tests
```
The restore regression suite exposed an ordering issue: SDK negotiation could
report a package downgrade before the existing failed-restore diagnostic. Discovery
now validates the successful restore marker before running negotiation and preserves
typed exporter errors raised through graph construction. All 12 restore-semantic
controls passed after the correction, including failed/partial restore rejection.
