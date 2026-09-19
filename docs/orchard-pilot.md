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

The target is a Release/Production build-server workflow. Development hot reload
is not part of this qualification. Build-worker paths in SDK-generated debug
metadata are acceptable; recovered applications must not require those paths.

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

### Step 4: mixed-framework executable analyzer dependencies

The complete host now exports all 202 selected projects successfully. The native
project-action path carries each selected framework and marks analyzer producers
and their dependency closures as implementation dependencies. Their full sealed
outputs remain executable, and implementation edits invalidate their consumers;
ordinary libraries retain API-based reuse. Aggregate legacy mode still rejects
these new graph capabilities.

An unchanged real Orchard net10.0 HealthChecks.Abstractions consumer and its
netstandard2.0 source generator build in six native Bazel sandbox actions. All
four consumer outputs match raw MSBuild byte for byte. A controlled generator
implementation edit emits an assembly metadata attribute: both compile actions
rerun, the consumer DLL changes, and all four outputs again match raw MSBuild.
These component tests do not bypass production discovery in the shipped path;
the temporary harness starts with an already validated preparation. Full owned
discovery, host runtime and independent remote-cache recovery remain open.

Per-project binding now writes only the four files consumed by replay, including
only the selected project's restore data. Dependency projects replay SDK-less
captured results. The two-project sample's bound consumer plan is 197,485 bytes
versus 1,247,180 bytes in the complete discovery plan. Source-role, stale-edge,
source-membership and immutable-template checks pass (five binding tests), as do
the analyzer-closure and legacy identity compatibility tests.

### Step 5: guarded full-host discovery and package preparation

The pinned 202-project CMS host passes production sandboxed discovery and full
C# graph preparation. A dedicated Orchard profile requires exact root anchors,
project/import bytes, and the pinned SDK import set. It adds no general permission
for arbitrary MSBuild XML. Generated NuGet package-path properties are admitted
without relaxing expression restrictions. All 287 package identities are covered;
266 additional archive pins record their exact hashes, payload roots and roles.

The MessagePack analyzer archive contains repeated path separators. Normalization
is allowed for pinned archives only; normalized duplicate entries and traversal
remain rejected. Verification-only discovery checks every package payload and
mutation without writing another copy of the entire NuGet closure. The targeted
archive, mutation and profile rejection checks pass.

The first full native execution attempt was intentionally interrupted before
compilation when repeated whole-graph plan parsing and duplicate generated
package copies became impractical. Indexed binding now reads only the selected
project's dependency records and retains source-role and identity validation. Its
output matches the legacy binder in the differential test. Payloads are limited
to the dependency closure, and generated BUILD files share a structural filegroup.
The full native build is still being qualified; these passing preparation checks
are not evidence of a working CMS runtime or fresh-worker cache recovery.

### Step 6: Web SDK result replay and Production runtime composition

The complete 202-project host now compiles and composes in the native component
harness. Producer results preserve the actual optional module/static-web-asset
query targets. Bundles retain the three SDK intermediate static-asset manifests,
with worker paths rebased on capture/replay. The pinned SDK's own manifest model
validates and recomputes its path-dependent hash. Round-trip, different-worker,
corruption and project-output ownership tests pass.

The exact Orchard import profile enables two scoped capabilities. Modules map
embedded development-source metadata to `/_/workspace` for the Production build.
Applications retain generated Localization outputs. Runtime composition also
preserves the empty `wwwroot` created by Orchard's application target; a marker
keeps that directory present through file-only cache transports. This is needed
by the media cache after site setup. Development physical-source reload is not
qualified.

An explicit upstream interceptor-generator patch replaces random generated class
names with a location-derived digest; see `tests/fixtures/orchard/README.md`.
With that patch, 134/136 artifacts in the 34-project theme chain exactly match
raw MSBuild under the same Release source-path normalization. The remaining
Queries DLL/PDB differences are explained by the standard Razor generator's
embedded worker paths and generated tag-helper IDs. All 23 differing generated
source documents match after accounting for those two differences. No custom
Razor compiler or post-build assembly rewriting is used.

The full component build preserved hashes for 808 own-project artifacts. Its
resumed run took 645.077 seconds with 337 executed sandbox actions and existing
component cache hits; it is neither a clean baseline nor a claimed speedup.
The component harness does not establish owned-workflow or remote-cache support.

The composed application served the setup page and embedded setup assets.
The Blog recipe created a SQLite database. This exposed the missing empty web
root; after adding it to the runtime copy, the home page, article, About page,
theme CSS, JavaScript and favicon all returned HTTP 200. SQLite integrity was
`ok` with 16 tables. The code fix has a composition regression test; qualification
of a freshly composed owned-workflow bundle remains a separate gate.

### Step 7: full-graph locked restore and repository acquisition

Locked restore now leaves framework selection to the authored projects and
accepts NuGet's `CentralTransitive` lock entries with the existing hash checks.
The large graph overflowed macOS's sandbox compiler when each source body had a
separate deny rule. An equivalent compact classification rule now blocks C# body
reads while retaining package and generated `obj` inputs. A real sandbox test
with 6,000 body declarations checks both denied and allowed reads, including a
workspace beneath an `obj` parent directory.

Bazel archive extraction now matches NuGet's `%2B` decoding in portable-framework
paths. A real repository-rule test covers both case variants and rejects a
collision with an already decoded path. The pinned Starlark checks pass. Locked restore and
guarded full-graph capture have passed; build/cache publication and fresh-worker
recovery are still being qualified.

The final source-role check also exposed repeated linear scans of all source
names for non-source inputs on macOS. It now constructs one case-insensitive set
and performs one lookup per input. The real graph with 5,615 declared source
names passes in 0.726 seconds including JSON loading. A 6,000-source/10,000-import
regression checks ordinary and case-aliased source/import rejection. This timing
is for that check alone, not end-to-end preparation.
