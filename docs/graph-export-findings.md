# Configured graph export findings

Milestone 1 acceptance is implemented and passing on Linux x86-64 CI.

Measured head: `a6f7f974ab1228af547a6060e46749be9a3608b3`.

Evidence:

- The contract and black-box suite were committed before the exporter; the first graph workflow failed because `tools/GraphExport` did not exist.
- The final graph acceptance run passed all 12 tests on Ubuntu 22.04 using the pinned .NET SDK 10.0.100.
- The exporter produces four compilation nodes for the diamond fixture, preserves only direct `ProjectReference` edges, distinguishes configured nodes by global properties, rejects path/symlink escapes, rejects unsupported multi-target/RID configurations, and performs no subject compilation.
- Independently restored checkouts produce identical normalized manifests. NuGet's checkout-derived `dgSpecHash` is normalized while the dgspec/assets/cache inputs remain declared.
- NuGet-generated `.nuget.g.props` and `.nuget.g.targets` are treated as derived restore outputs rather than independent import identity because `MSBuildAllProjects` does not provide a stable ordering/presence contract for those generated files.
- Traversal entry points expand only to their direct configured roots; downstream reachable projects remain graph nodes, not entry points.

Remaining limitations:

- net10.0, Debug/Release, SDK-style C# only.
- Restore and tool acquisition remain preparation steps outside export/build actions.
- MSBuild evaluation is trusted code and not a security sandbox.
- Multi-targeting, RIDs/native assets, specialized SDKs, arbitrary custom target behavior, remote caching and remote execution remain unproven.
- The exporter establishes a local manifest contract; it does not yet generate or execute Bazel actions for the graph.
