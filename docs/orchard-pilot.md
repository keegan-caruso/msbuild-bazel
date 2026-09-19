# Orchard Core support pilot

## Acceptance workload

Pinned upstream: OrchardCMS/OrchardCore at
`04467a3438d4255627c1a478598a1585b3ff2947`.
Entry: `src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj`.
Host: macOS ARM64, Nix .NET SDK 10.0.400, Release, two MSBuild nodes.
The upstream SDK roll-forward accepts this SDK without changing source.

The unchanged host restores and builds successfully. MSBuild evaluation discovers
202 projects: 201 net10.0 and one netstandard2.0 source generator. There are
5,123 evaluated C# compile items, 1,400 declared project-reference items, 200
analyzer project-reference items, and 287 restored packages. Outer framework
coordination adds another 202 evaluation nodes; these are not extra compilations.

## Initial measurements

| Operation | Seconds |
| --- | ---: |
| Restore, initially empty dedicated package cache | 21.793 |
| Clean Build after restore | 49.921 |
| Warm no-op Build 1 | 13.385 |
| Warm no-op Build 2 | 12.619 |
| Warm no-op Build 3 | 12.365 |

These are sequential single-machine samples, not Bazel speedup measurements.
Build uses upstream analyzer/generator settings and ordinary compiler-server
behavior. No frontend asset regeneration, Publish, application setup or runtime
qualification is included in this initial baseline. Initial restore with a forced
global TargetFramework hit a NuGet static-graph null-reference error; letting
upstream choose its frameworks succeeds. Do not force all projects to net10.0.

## Support work in progress

Full support requires all of these gates, in order:

1. Validate central package versions and transitive pinning against actual NuGet
   assets and consumer dependency snapshots; reject stale/partial restores.
2. Preserve framework selection and analyzer dependency roles, including outer
   framework coordination and the netstandard2.0 generator.
3. Qualify declared Web/Razor SDK imports, package payloads, framework references,
   Orchard module targets and non-C# input ownership without bypassing isolation.
4. Capture/replay module query results, Razor outputs and static/module assets;
   retain real generator implementations in compilation dependencies.
5. Compare native action outputs with raw MSBuild, launch the recovered host,
   and exercise Razor/module/static asset behavior.
6. Prove fresh-worker remote hits and changed C#/generator/Razor/asset invalidation,
   then measure cold, no-op and changed builds against the same raw workload.

The initial production XML guard rejects the Web SDK, root build properties,
central package properties and Orchard module targets. A direct graph-export
probe first rejects central transitive pinning. None of these guards has been
removed to obtain a benchmark. This workload is not yet supported by the Bazel
project-action pipeline.

### Step 1: central transitive package pinning

The exporter now compares evaluated central package settings and the complete
central version table with both project assets and every consumer restore
snapshot. Central nonfloating version ranges retain NuGet's resolved version
semantics; selected transitive versions must satisfy their central constraints.
SDK/package execution and archive checks remain unchanged. VersionOverride is
still rejected. This is a restore-validation extension, not Orchard qualification.

Validation: the 20-case restore semantics suite passes. Nine focused central
cases were exercised; the added resolved-version corruption control initially
hit an earlier SDK missing-package check. With both real package versions present,
it now reaches and passes the intended central-pin rejection. C# formatting is
checked independently. Evidence includes `orchard-pilot-evidence.json`.

### Step 2: generator restore metadata

Orchard's unchanged netstandard2.0 generator now exports one configured node and
873 declared inputs. The exporter accepts the SDK's specific implicit
NETStandard.Library `2.0.0-*` request only with the auto-referenced restore marker
and resolved 2.0.0 identity. Broader floating requests remain rejected. Evaluated
GlobalPackageReference items retain the SDK's runtime/build/native/content/analyzer
filter and PrivateAssets=All, with unchanged restore comparison.

All four selected-framework tests and the focused global-package restore test
pass. The generator export succeeds against the pinned real checkout. No build
or remote-cache support claim follows from export alone.

### Step 3: native generator build and NuGet build-asset exclusion

The real generator now builds via production C# graph preparation and the native
Bazel `graph_project` sandbox. Its DLL, PDB, XML documentation and deps.json are
byte-identical to raw MSBuild using the same PathMap, Deterministic and in-process
compiler settings. SourceLink and analyzers remain enabled as authored. Three
additional archive pins cover CodeStyle 5.9.0, NETStandard.Library 2.0.0 and
StyleCop 1.1.118; existing matching pins cover the other 16 packages.

The full host's ExcludeAssets=build;buildTransitive declaration is also validated
against NuGet's effective include mask, with a successful prepare and stale-restore
negative control. Other unqualified filters remain rejected. The existing
`graph_project` smoke test is not remote-cache qualification of the newer owned
project-action pipeline; mixed-framework analyzer edges still need integration
there. Native generator build: one darwin-sandbox action, 7.385s Bazel wall time
including startup/analysis; this isolated sample is not a performance comparison.

The full export then reached explicit ProjectReference PrivateAssets=none.
Validation now checks that metadata in both the project's restore and each
consumer snapshot. Its partial-restore negative control passes; removing the
attribute requires a complete restore before graph publication.
