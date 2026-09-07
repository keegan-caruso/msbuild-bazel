# Reject stale consumer restore closures

A partial restore could previously publish a fresh graph and generated plan
whose consumer package closure no longer matched dependency semantics. Checking
each project's direct PackageReferences against its own assets was insufficient.
This fix validates each consumer's recorded dependency requests before publishing.

## Native reproduction before the fix

On macOS ARM64 with pinned Nix SDK 10.0.100 and Bazel 8.4.2 at `737e29f`:

1. Restore the managed package diamond with Left's ordinary PrivateAssets default.
2. Change Left's PackageReference to `PrivateAssets=all` and restore only Left.
3. Freshly export the whole graph, prepare it and build in native sandbox actions.

The fresh export and preparation succeeded. App's generated package manifest
still contained Spike.Binary and Spike.Leaf, and its executable printed
`shared-v1:left/package-v1|shared-v1:right`. Its direct PackageReference set was
empty and matched its stale assets, so the earlier per-node check accepted it.

After restoring the whole graph, App's package manifest was empty. Both generated
execution and a separate ordinary isolated MSBuild build then failed at runtime
with the expected missing Spike.Binary assembly (exit -6). This is the established
PrivateAssets=all baseline: the earlier successful stale runtime was incorrect.
Evidence is retained at `/private/tmp/restore-closure-repro`, including both
manifests, raw build/runtime logs and `report.json`.

The consumer App dgspec still recorded Left's old direct request without
`suppressParent`; Left's newly restored own dgspec recorded `suppressParent=All`.
This provides a per-consumer snapshot of requested semantics without inferring
NuGet's resolved transitive versions.

A separate natural failed-restore case is retained under
`/private/tmp/restore-closure-repro/failed-restore`. Initially App and Left both
request Binary 1.0.0. Upgrade and restore only Left to 1.0.1, then restore the
whole graph: App restore fails `NU1605` for the downgrade. Its dgspec is updated,
but `project.nuget.cache` records `success=false`. Snapshot comparison alone
still accepted a fresh export, so the fix also requires a successful restore
marker. These failures were produced by ordinary NuGet operations, not by editing
restore JSON.

## Validation boundary

For each consumer, the exporter walks its configured dependency closure and
compares each dependency's evaluated direct PackageReference set, exact requested
version, PrivateAssets and supported asset filters with the dependency ProjectSpec
recorded in that consumer's `.nuget.dgspec.json`. It also compares evaluated direct
ProjectReference paths with recorded restore references; removing an edge cannot
leave an old transitive closure silently accepted. Missing snapshots, unsuccessful
restore markers or mismatching specs reject with `stale-restore` before graph
publication. Preparation invokes the exporter during revalidation, so it cannot
publish a replacement plan either.

The comparison uses requested constraints, never equality of resolved transitive
versions. A positive control permits App resolving Binary 1.0.1 while Left resolves
1.0.0. Project paths are canonicalized using the existing directory helper,
including macOS `/var` and `/private/var` aliases. Closure walking uses an explicit
stack rather than recursion.

NuGet's ProjectSpec map is keyed by project path. If same-path configured nodes
have different direct package requests, it cannot unambiguously represent both;
that shape rejects `unsupported-configured-restore`. Package-free configured
variants remain valid. Explicit ProjectReference PrivateAssets/IncludeAssets/ExcludeAssets metadata and
ReferenceOutputAssembly=false reject explicitly in this restore-validation slice.
The existing configured Flavor metadata remains supported; no equality of all
transitive package versions or broad NuGet compatibility is claimed.

## Focused acceptance

```sh
python3 -m unittest discover -s tests/graph_packages -p test_restore_semantics.py -v
python3 -m unittest discover -s tests/graph -v
```

All 12 restore-semantic tests passed in 62.442 seconds on macOS. They cover partial
PrivateAssets/version restores, removed packages, removed project edges, missing
snapshots, a failed NU1605 restore, and valid differing consumer resolution. Fresh
exports fail without manifests, attempted replacements do not publish, and original
plans remain byte-identical. A full successful restore subsequently prepares.
All 14 exporter regressions passed again in 63.256 seconds against the final
committed implementation, including canonical path aliases, independent relocation
and selected-inner cases.

With the native sandbox available, also ran:

```sh
python3 -m unittest discover -s tests/configured_execution -v
```

Both configured execution tests passed in 71.017 seconds at stable commit
`38bfb92`, preserving six-node Flavor execution, selective edge convergence,
byte-identical relocated recovery and selected-inner behavior. Evidence is under
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/` in
`configured-execution-79anw0qi/probe` (configured graph) and
`configured-execution-jxzn2bt7/probe` (selected inner). These runs used native
macOS sandboxing; no Linux result is claimed for this extension.

## Final integration regression

At integrated `6563e3c`, the full package-cache suite passed all 13 tests in
217.776 seconds and the complete PrivateAssets/restore-state suite passed all
14 tests in 161.561 seconds on native macOS ARM64. These runs include the
configured-node implementation and iterative dependency-closure fix. Commands:

```sh
python3 -m unittest discover -s tests/graph_cache_full -v
python3 -m unittest discover -s tests/graph_packages -v
```

Retained cache evidence is
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/msbuild-graph-cache-czm716kd/probe`.
The combined local logs are `/private/tmp/final-package-cache.log` and
`/private/tmp/final-privateassets.log`. The pinned environment check and diff
whitespace check also passed. Linux qualification remains blocked by the GitHub
account billing/spending-limit gate until jobs can start.
