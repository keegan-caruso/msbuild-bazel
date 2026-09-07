# R04 required inputs: pinned Serilog ordinary oracle

This is preparation for adapter support, not Serilog adapter acceptance. The
oracle uses revision `49b5339ce85385dc52d4d8e8f2b8308becf23506`, SDK 10.0.100,
and the existing acquired checkout/package cache. It archives the exact commit
into a new directory, copies the package cache, then restores and builds only
`src/Serilog/Serilog.csproj` with global `TargetFramework=net10.0`. The original
multi-target declaration is retained byte-for-byte. No upstream source or package
version is rewritten and no new upstream download was needed for this run.

Run the executable ordinary SDK oracle after the existing
[acquisition baseline](real-project-pilot.md) has prepared its source/packages:

```sh
SPIKE_SERILOG_SOURCE=/path/to/serilog-baseline/source \
SPIKE_SERILOG_PACKAGES=/path/to/serilog-baseline/packages \
python3 -m unittest discover -s tests/serilog_inputs -v
```

The test is explicitly skipped without both acquisition paths; an unconfigured CI
run is not acceptance. `tests/serilog_inputs/probe.py` also accepts those paths and
`--output` directly. All restores occur outside build actions. The test retains
resolved item metadata, input/generated-source hashes, full command logs and a
reflection/logging report in `serilog-inputs-*/probe`.

## Measured required library inputs

The resolved post-Build inventory contains eleven analyzer/generator assemblies:

| Origin | Selected assemblies |
| --- | --- |
| SDK analysis | Microsoft.CodeAnalysis.CSharp.NetAnalyzers.dll; Microsoft.CodeAnalysis.NetAnalyzers.dll |
| Implicit Microsoft.NET.ILLink.Tasks 10.0.0 | ILLink.CodeFixProvider.dll; ILLink.RoslynAnalyzer.dll |
| PolySharp 1.15.0 | PolySharp.SourceGenerators.dll |
| SDK net10.0 reference pack | ComInterfaceGenerator, JavaScript.JSImportGenerator, LibraryImportGenerator, SourceGeneration, System.Text.Json.SourceGeneration, System.Text.RegularExpressions.Generator |

The SDK-supplied assemblies remain toolchain inputs. Both NuGet packages are
private to the library. `IsAotCompatible=true` introduces ILLink implicitly;
PolySharp is an explicit `Version="1.15.0" PrivateAssets="All"` reference.
PolySharp's `build/PolySharp.targets` imports compiler-visible generator options;
its package also contains a buildTransitive target. This is not a ref/lib-only
package. The generated editorconfig is action-produced data derived from those
options, framework/defines and project paths. No AdditionalFiles were resolved.

With the actual upstream options, PolySharp emits
`System.Runtime.CompilerServices.IsExternalInit.g.cs` and
`System.Runtime.CompilerServices.RequiresLocationAttribute.g.cs`. The oracle
requests compiler-generated-file emission solely to inspect these normally
in-memory compiler outputs, under the existing obj directory. A fresh Rebuild
with `PolySharpExcludeGeneratedTypes=System.Runtime.CompilerServices.IsExternalInit`
emits only RequiresLocationAttribute, proving a compiler-visible option changes
the generated source set without changing package bytes. Generated source
must remain an output of the compile action, never a precomputed preparation input.

The signed DLL exposes public key token `24C2F752A8E58A10` and contains exactly the
`ILLink.Substitutions.xml` resource. Its resource bytes match the checked-in XML;
its logical name is meaningful metadata, not just a file path. An independent
ordinary consumer logs `Hello "Ada"` through a custom sink, exercising actual
Serilog behavior. XML documentation output remains enabled by shared props.

Required non-source workspace inputs include `Directory.Build.props`, its
`Directory.Version.props` import, `assets/Serilog.snk`, and the embedded XML.
The version import supplies VersionPrefix 4.4.1. The key is read via a property,
not Compile/Content/Analyzer, and the resource has explicit LogicalName metadata.
`MSBuildAllProjects` alone did not enumerate all these inputs in the post-build
query; retain actual evaluated import discovery rather than relying on that list.

## Proposed bounded declared contract

1. Keep configured path-plus-global identity and existing selected framework.
   Preserve resolved package versions and archive hashes without rewriting bare
   upstream versions to `[exact]`. Validate the evaluated requested range against
   restore; unsupported floating/range semantics must remain explicit. Implicit
   SDK references and inactive conditional references must not be treated as
   literal active inline references by the raw XML guard.
2. Add resolved compiler analyzer/generator assembly paths and metadata to the
   discovery surface after the SDK's ResolveReferences/ResolvePackageAssets
   boundary, without running CoreCompile. Hash package archives, selected targets
   and assembly dependencies. Retain package target imports that supply options.
   The eleven resolved DLLs are evidence for this slice, not a generic rule that
   copying only the primary generator DLL provides its dependency closure.
3. Declare signing-state evaluation plus the key when signing is enabled, resource
   path plus LogicalName, and existing shared imports. Include user editorconfig
   and AdditionalFiles if actually resolved. Generate SDK analyzer config in the
   action with its normal values; paths require the existing normalization policy.
4. Preserve compiler-generated sources as compile outputs/diagnostic evidence.
   Stage signed assembly, reference assembly, PDB and documentation in the normal
   configured output directories. Do not expose generator intermediates as inputs
   to another action without an explicit future contract.

The missing-key control demonstrates ordinary upstream behavior: deleting the key
makes `SignAssembly` false because its condition uses Exists, and Rebuild succeeds
with an empty public key token. An old signed manifest must reject that missing
declared key. A fresh export must notice the signing-state change and either
reproduce the unsigned build or explicitly reject it as outside the signed pilot.
Mandatory signing is a pilot scope choice, not generic MSBuild semantics.

## Remaining acceptance gaps

Current `PackageRestoreValidation` requires bracket-exact evaluated versions,
including implicit ILLink; Python/runner raw inline validation also rejects bare
versions and inactive conditional source references. `graph_packages` rejects
analyzers, build and buildTransitive archives. Evaluation-only Analyzer collection
does not establish the post-resolution set above. Key discovery is missing.
These are production blockers, not reasons to disable generators or signing.

This library oracle is deliberately smaller than the approval-test entry. The
pinned prior approval restore includes twenty packages plus the Serilog project.
Its closure includes xunit.analyzers, test-host and xunit targets, Shouldly,
EmptyFiles, CodeCoverage and System.Management runtimeTargets, beyond this initial
library input slice. The existing approval file must be declared for an isolated
test action. Approval-project selected-inner dependency graph, runtime asset
selection, adapter API approval, logging parity, source/key/resource/import/
generator-option invalidation, failed-input publication, relocation and recovery
still require acceptance. The package range policy must cover the real pinned
source without editing it. Publishing, trimming/AOT execution and general generator
combinations remain separate work.

All new observations here are native macOS ARM64 ordinary-MSBuild behavior.
Linux qualification is blocked by the repository CI billing gate; no Linux,
remote-cache or adapter result is claimed.

The final delivered opt-in test passed in 4.548 seconds with evidence at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/serilog-inputs-qb4lrql9/probe`.
It asserts signed resource/logging behavior, exact selected package/analyzer
inventory, two generated sources, option-driven source removal, unchanged
upstream framework declaration and the ordinary unsigned missing-key control.
Python compilation and diff whitespace checks also passed.
