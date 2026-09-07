# Serilog API approval: next bounded acceptance slice

Inspection of the pinned existing source and restored assets identifies two
separate next steps. No package-policy expansion or upstream changes are part
of this inventory.

## Independent library API oracle

The smallest extra library oracle can call PublicApiGenerator 11.1.0 with the
exact options in `test/Serilog.ApprovalTests/ApiApprovalTests.cs`:
`IncludeAssemblyAttributes=false` and
`ExcludeAttributes=["System.Diagnostics.DebuggerDisplayAttribute"]`. Its pinned
runtime closure from the existing assets is Mono.Cecil 0.11.5 and System.CodeDom
8.0.0. The test must explicitly declare `Serilog.approved.txt` and compare the
same generated API text against it. Positive original and negative public API
mutation controls should run against both ordinary and adapter DLLs, including
a recovered DLL after producer deletion.

A direct comparison oracle would establish library API approval parity; it would
not establish unchanged upstream xUnit/Shouldly test-project execution.

## Unchanged upstream approval-test project

The project has one Fact and five direct package references:
Microsoft.NET.Test.Sdk 17.11.1, xunit.runner.visualstudio 2.8.2, xunit 2.9.2,
Shouldly 4.2.1 and PublicApiGenerator 11.1.0. Existing `net10.0` assets contain
20 package libraries plus the Serilog project. Additional behavior beyond the
current library slice includes:

- Microsoft.NET.Test.Sdk's `InitialTargets=GenerateProgramFile` adds a package-owned
  C# Compile item. Post-resolution discovery must declare that actual source.
- xunit.analyzers 1.16.0, the Visual Studio runner and TestHost require separate
  analyzer, adapter and runtime payload qualification. TestPlatform ObjectModel
  and TestHost select 65 localized resource assemblies.
- EmptyFiles' buildTransitive target adds `ContentWithTargetPath` copied from the
  package. Shouldly depends on DiffEngine and EmptyFiles, and DiffEngine brings
  System.Management 6.0.1 with a Windows-specific runtimeTarget. Do not silently
  omit a restored asset role because the happy-path test did not invoke it.
- The imported TestSDK/xUnit/TestHost/CodeCoverage/Shouldly targets are executable
  MSBuild behavior. A Build action does not establish VSTest action semantics,
  complete test-host runtime closure, result publication or failure propagation.
- `Serilog.approved.txt` is runtime test data, not a default compiler input. Its
  path and hash need an explicit test-action declaration and negative controls.

Upstream sets `DeterministicSourcePaths=false`. Shouldly's
`CapturePathMapsForShouldly` target is consequently disabled, while the current
adapter independently forces compiler PathMap to `/_/workspace`. The mapped PDB
source path may therefore disagree with the actual approval-file location.
Test-data staging and Shouldly's path-map behavior require a concrete test rather
than assuming that the source checkout is still available. This is an identified
contract question, not a measured adapter test failure.

Evidence inspected: the unchanged project/test source and
`/private/tmp/msbuild-serilog-baseline-3/source/test/Serilog.ApprovalTests/obj/project.assets.json`,
plus the pinned package target files in its acquired package cache. Existing
ordinary approval success is documented in `real-project-pilot.md`. No new
upstream-test native/isolated acceptance is claimed here.
