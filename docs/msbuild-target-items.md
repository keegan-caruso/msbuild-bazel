# Explicit MSBuild target results and Orchard module assets

Producers can export named MSBuild target results. Bazel owns the result artifact;
consumers map selected results to explicit MSBuild items at an explicit target
hook. No rule contains Orchard-specific names or behavior.

```starlark
msbuild_library(
    name = "Module",
    # project, framework, sources, dependencies, imports, assets ...
    export_targets = {"GetModuleProjectName": []},
)

msbuild_target_items(
    name = "module_names",
    deps = [":Module"],
    target = "GetModuleProjectName",
    item_type = "ModuleProjectNames",
    before_targets = ["ResolveModuleProjectReferences"],
)

msbuild_binary(
    name = "App",
    # project, framework, sources, dependencies, imports ...
    deps = [":Module"],
    items = [":module_names"],
)
```

The export dictionary maps target names to metadata names to preserve; an empty
list exports item identities alone. Results run after Build in the same MSBuild
request/evaluated project. Consumers do not reevaluate producer projects or invoke
the producer target. Result changes invalidate consumers even when reference
assemblies do not change. `target_results` is also an output group.

Without `before_targets`, items are added during evaluation. With a hook they are
added just before the named target(s). Choose a hook before the actual consuming
target; `GenerateAssemblyInfo` is too late to affect its prerequisite that collects
assembly attributes. Existing project target logic remains responsible for using
the items. This is an explicit replacement for selected cross-project target
queries, not automatic interception of arbitrary MSBuild task calls.

## Qualified boundary

- Only scalar item identities and explicitly selected scalar metadata are exported.
  Paths and MSBuild expressions reject. File-valued results require a future typed
  artifact contract; producer-local paths are never silently serialized for reuse.
- Unknown/missing targets reject. Target items cannot replace source, reference,
  analyzer, package, or framework declarations.
- Assembly build rules export results; restore-only rules cannot.
- Existing target execution remains sandboxed with declared file inputs.

## Linux evidence

SDK 10.0.400, Bazel 8.4.2, Linux ARM64 container, persistent workers:

`tests/explicit_msbuild/target_items.py` passes item identity/metadata handoff,
result-edit invalidation, unknown-export/missing-target rejection, source-item
rejection, absolute-path rejection, recovery, and consumer compilation with a
cached producer result. The cache control reports one producer disk-cache hit
and one consumer worker action.

`tests/explicit_msbuild/orchard_compatibility/module_assets.py` copies the unchanged
module/application targets and five manifest attribute source files from Orchard
commit `04467a3438d4255627c1a478598a1585b3ff2947` into a small fixture:

- Raw MSBuild and Bazel both report the referenced module name and marker, read
  its embedded asset, and instantiate/execute its compiled Razor view.
- Resource-only and Razor-only edits produce changed runtime output.
- After deleting the original Bazel output tree, a consumer at a different
  workspace path compiles using two disk-cache hits (manifest/module) and one
  worker action (consumer). Module discovery, resource reads and Razor rendering
  still pass.
- The fixture uses explicit EmbeddedResource/RazorGenerate items, Link metadata
  for stable module-relative asset names, and the normal late Directory.Build.targets
  import phase for Orchard module targets.

Run after initializing the explicit acceptance workspace:

```sh
python3 tests/explicit_msbuild/target_items.py /tmp/target-check
python3 tests/explicit_msbuild/orchard_compatibility/module_assets.py \
    /tmp/target-check /path/to/pinned/orchard
```

## Remaining Orchard qualification

This is a focused compatibility result, not a full 202-project CMS build or a
performance measurement. Next, declare the full graph's resource/content inputs
and module result edges, then build and smoke-test the actual CMS application.
Static web asset publishing, development-time source-path fallback, full Razor
page discovery, RID/native assets, and full CMS startup from a remote cache remain
unqualified. The demonstrated cache is a local disk cache with relocated/deleted
producer state, not a remote execution/cache service. Orchard's own module asset
attributes can still contain original debug source paths; the tested runtime uses
embedded assets rather than that development fallback.

Compact test reports and cache excerpts are checked in under
[evidence/orchard-explicit-extensions (historical)](https://github.com/keegan-caruso/msbuild-bazel/blob/46d7f37b5cf36e62453a2a511697562107ce6ee2/docs/evidence/orchard-explicit-extensions/README.md).
