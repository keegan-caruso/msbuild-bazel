# Configured project graphs

A graph node is a project path plus its global properties, including its selected
framework and configuration. The production rules keep these declarations in
BUILD files. The OSS fixture inventory is test scaffolding; it is not part of
application builds.

## Contracts

- `msbuild_project` provides a facade over explicit framework variants.
- `assembly_selections` resolves a convergence point to a declared variant,
  retaining each producer's original compiler inputs. Assembly and NuGet identity
  mismatches fail; API compatibility remains the author's responsibility.
- `implementation_deps` corresponds to `ProjectReference PrivateAssets="all"`:
  compiler references stay private, while runtime dependencies remain available.
- Restore identities include implementation/public frameworks, configuration and
  explicit global properties. Filesystem paths use a hash of that identity.
- Runtime staging uses the application's SDK platform manifest to exclude strictly
  older inherited **package** assemblies supplied by the framework. Equal/newer
  versions and project/data file collisions retain the existing checks. This is
  a bounded rule, not a replacement for the SDK's complete conflict resolver.

See the [API](explicit-bazel-rules.md#configured-branches-and-assembly-selection)
for declarations and rejection rules. The visibility distinction follows the
[SDK's transitive-reference behavior](https://learn.microsoft.com/en-us/dotnet/core/project-sdk/msbuild-props#disabletransitiveprojectreferences);
the runtime rule reads `PackageConflictPlatformManifests` produced by the pinned
SDK's `Microsoft.NET.ConflictResolution.targets`.

## Small controls

`tests/explicit_msbuild/configured_graph.py` builds this graph with raw MSBuild,
then exercises the generated explicit BUILD declarations:

```text
App/net10.0 -> Core/net10.0
           -> Helper/netstandard2.1 -> Core/netstandard2.1
```

Raw compilation selects each compatible Core reference. At runtime both branches
use the modern Core implementation and print `10:10`. The Bazel control first
rejects the ambiguous closure, then selects the modern variant explicitly.
Controls cover no-op, body/API edits, mismatched assembly versions, restoration,
fresh-cache recovery, and persistent-worker input remapping.

`oss/inventory_controls.py` checks edge property overrides, removed properties,
shared nodes and stable IDs when entry order changes. The inventory runs the
SDK's `PrepareProjectReferences` target after restore, then retains only declared
edges: SDK-added transitive edges must not become new direct dependencies.

`implementation_deps.py` compares a private dependency with raw MSBuild: downstream
source cannot use its types, but a public wrapper can call it at runtime. A BUILD
visibility declaration that disagrees with the project fails. The existing
`configured_restore.py` additionally covers distinct frameworks, paired contracts,
shared package identities, and paired/direct views of one implementation.

```sh
USE_BAZEL_VERSION=9.2.0 python3 tests/explicit_msbuild/configured_graph.py \
  /tmp/configured-92 --executor grpc://WORKER_IP:8980
python3 tests/explicit_msbuild/oss/inventory_controls.py \
  /tmp/configured-92/probe/bin/Release/net10.0/Inventory.dll /tmp/inventory-controls
python3 tests/explicit_msbuild/implementation_deps.py /tmp/private-projects
```

Use fresh directories and the configured Linux SDK/Bazel environment. Repeat the
configured graph with `USE_BAZEL_VERSION=8.8.0`. Remote controls disable local
fallback; the local controls require the Linux persistent-worker environment.

## Results

The diamond's raw parity, edit, identity rejection, fresh-cache and persistent
worker controls passed on Bazel **8.8.0 and 9.2.0**. Private-reference controls
and the seven-case configured restore regression passed on 9.2.0. Inventory
controls preserve two root configurations and one shared child. Rule analysis
passes **39 tests** on each Bazel baseline; the runner suite passes **34 tests**.
See [compact evidence](configured-graphs-evidence.json).

## Scope

Inventory generation requires restored assets for each evaluated configuration.
It does not acquire configuration-specific package locks automatically. Multiple
configurations with different package assets need separately prepared assets.
A consumer still selects one direct configuration per project. Selection does not
prune variant-specific descendants, packages or data; remaining conflicts fail.
Partial `PrivateAssets` lists on project references are unsupported.

The [Avalonia qualification](avalonia-remote-execution.md) exercises the actual
mixed-framework Markup suite. This does not imply support for the whole Avalonia
repository, all MSBuild conflict policies, other platforms, or other SDK versions.
