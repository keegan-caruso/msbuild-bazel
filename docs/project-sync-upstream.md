# Generator expansion: ASP.NET Core and dotnet/runtime

This is a compatibility inventory and small-fixture qualification, **not a new
upstream build/test qualification**. Existing handwritten upstream adapters remain
independent of `msbuild_sync`.

## Pinned starting slices

| Repository | Revision | First slice | Next inspection slice |
| --- | --- | --- | --- |
| ASP.NET Core v10.0.0 | `7387de91234d3ef751fa50b3d1bfede4130213ff` | ObjectPool library and ObjectPool.Tests | Http.Abstractions |
| dotnet/runtime v10.0.0 | `60629d14374c56f1cb51819049ad1fa529307f8d` | System.IO.Pipelines library and tests | System.Collections.Immutable |

ObjectPool is small but uses shared linked sources, framework properties and the
repository's bare-reference conversion. Pipelines adds implementation-assembly
references, common test infrastructure and source-built framework dependencies.
Neither is an isolated ordinary SDK project despite its small entry file.

Source inspection uses these original project files plus root `Directory.Build.*`,
`eng/targets/ResolveReferences.targets` (ASP.NET Core), and
`eng/Analyzers.targets`, `eng/testing/xunit/xunit.props` and the library-level
imports (runtime). The inventory does not pretend XML inspection resolves conditions.

## Observed first failures

On macOS ARM64 with SDK 10.0.400, the unbootstrapped ASP.NET Core checkout fails
all three entry probes because `artifacts/bin/GenerateFiles/Directory.Build.props`
is absent. The runtime checkout evaluates, then all three probes stop at
`Item requires explicit mapping: WorkloadSdkBandVersions`. This does not mean
allowing that one item would make the graph supported: imported custom targets,
Arcade inputs, reference redirection and generated outputs still need contracts.
The first runtime probe also exposed a missing file in the sparse checkout; adding
the referenced generator sources removed that checkout issue before recording results.

The generator ran no targets and did not alter the upstream project files.
[Recorded probe results](project-sync-upstream-evidence.json) include source hashes.

## Compatibility matrix

| Construct | Evidence in selected repositories | Generator status after this change |
| --- | --- | --- |
| Imported framework properties and conditional Compile/ProjectReference items | Both repositories | Evaluation already supported; project mappings now select a declared framework subset and explicit properties |
| Shared Compile files with Link/LinkBase | ObjectPool, Pipelines, Immutable | Explicit sources plus metadata-preserving `msbuild_items`; synthetic build qualified |
| PackageReference PrivateAssets=all/none | Runtime analyzers/test infrastructure; ASP.NET reference conversion | Emitted as `package_private_assets`; central versions and exact package bindings retained |
| Simple resources, additional files and copied content | Both repositories' wider library/test infrastructure | Explicit item declarations; existing-file inputs only, bounded metadata |
| Bare Reference-to-project/package conversion | ObjectPool.Tests, Http.Abstractions; runtime reference machinery | Needs an explicit resolved-reference mapping; no target execution or name guessing during sync |
| Arcade SDK and repository bootstrap | Both root import chains | Needs declared SDK/package acquisition and Bazel-produced bootstrap inputs; not bypassed |
| Custom tasks and resource/source generators | Both import chains | Existing rule primitives available, but sync needs tool/generation mappings; still rejected |
| InternalsVisibleTo items / implementation references | ObjectPool friend declaration; Pipelines SkipUseReferenceAssembly | Rule support exists; generator needs explicit friend/assembly-selection integration |
| NuGet IncludeAssets/ExcludeAssets, partial PrivateAssets, VersionOverride | Runtime test tooling and ASP.NET reference conversion | Still rejected; asset-role semantics need separate contracts and tests |
| Native/runtime layouts, reference/implementation pairs | Runtime source-built test host | Existing explicit rule support; outside automatic sync scope |

Framework subsets never invent a framework or silently remove a dependency.
Unselected variants are omitted only when the author explicitly lists the desired
frameworks. Each dependency can have its own mapping. The selected graph still
needs compatible dependency variants, which Bazel validates.

## Next integration gates

1. Model bootstrap and NuGet SDK acquisition as declared inputs/actions. Inventory
   the complete evaluated imports after bootstrap; do not add a blanket custom-target
   allowlist or suppress unsupported items to get a green synchronization.
2. Add exact resolved-reference/tool mappings, including project-built analyzers,
   generated resources and implementation-assembly selection. Prove each in a
   synthetic before applying it to either repository.
3. Synchronize ObjectPool plus tests and compare build/test outcomes. Then apply
   the same process to Pipelines plus tests on the qualified Linux environment.

Full upstream execution, native builds, cache recovery and performance measurement
are subsequent steps, not evidence from this inventory.

## Reproduce

Use disposable checkouts at the exact revisions above. Include `eng`, the selected
source directories and their imported generator/shared-source directories in sparse
checkouts, or use full checkouts.

```sh
bash scripts/dotnet.sh build tools/ProjectSync -c Release
python3 tests/project_sync/inventory.py /path/to/aspnetcore /path/to/runtime /tmp/inventory.json
python3 -m unittest discover -s tests/project_sync -v
python3 tests/project_sync/compatibility.py /tmp/new-sync-compatibility
```

The inventory records evaluation errors without treating them as supported builds.
The compatibility fixture uses a locally packed, checksum-locked package, selected
net10.0 variant, linked source, conditional source, embedded text resource, additional
file and copied file. It checks successful execution, resource edits, private-package
compile rejection, drift detection and public-package recovery after synchronization.

### Results

On macOS ARM64 / SDK 10.0.400, all nine compatibility-fixture steps passed their
expected contracts on Bazel 8.8.0 and 9.2.0. The private-consumer and stale-mapping
steps deliberately fail; all other steps succeed. The app prints
`7:hello:extra`, then `7:changed:extra` after the resource edit, and `7` when
the package is made public and directly used by the consumer. Copied content is
checked on disk and linked sources compile without duplicate-source warnings.

Twenty generator controls, 35 runner unit tests, .NET style/build checks and
Starlark/toolchain checks pass. The new controls also reject unsupported metadata
on SDK-globbed sources and inherited PackageReference metadata. No GitHub CI,
Linux qualification, upstream test execution or performance measurement was run.
