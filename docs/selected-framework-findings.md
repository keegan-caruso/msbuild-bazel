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
