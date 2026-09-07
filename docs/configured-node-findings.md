# R03 configured-node baseline and implementation inventory

Status: authored ordinary-MSBuild fixtures and measured macOS baseline only.
No generated graph, replay, Bazel cache, Linux or Serilog adapter acceptance is
claimed here. This track starts from `fd96f5e`; it changes fixtures, tests and this
record without changing production preparation or execution.

## Executable baseline

Run with the pinned SDK available through the existing environment override:

```sh
python3 -m unittest discover -s tests/configured_nodes -v
```

The suite copies `tests/fixtures/configured-nodes` into new system-temporary
`configured-baseline-*` directories. It restores, builds with normal MSBuild,
runs App directly, and retains every command log. Worker reuse is disabled.
No build writes into the checked-in fixture. NuGet acquisition is outside build.

Measured on native macOS ARM64 on 2026-09-07 UTC with Nix SDK 10.0.100:
all three tests passed in 10.591 seconds. Evidence is retained locally at
`/private/var/folders/__/z2sj57556cgfrkvbdznlvdt40000gn/T/configured-baseline-4bg48f_k`.
The expected isolated failure is an asserted negative control, not a skipped or
passing application build. No Linux run has been performed for these fixtures.
The fixture is newly authored from the semantic shapes described in the
[pinned MSBuild configured-edge references](coverage-project-selections.md#msbuild-configured-edge-fixtures);
no upstream test implementation was copied.

The direct-edge graph is:

```text
App -> Left  -> Shared [Flavor=red]  -> Common [Flavor removed]
    -> Right -> Shared [Flavor=blue] -> Common [Flavor removed]
```

Left/Right set `AdditionalProperties="Flavor=red/blue"` on their Shared edge.
Shared uses `GlobalPropertiesToRemove="Flavor"` on its Common edge. The Common
project's ordinary default is `plain`; it is not a global-property override.
Shared uses distinct assembly names, `bin/<flavor>/Release/net10.0` outputs and
`obj/<flavor>` intermediate/restore directories. All `obj/**` and `bin/**` are
excluded from default source globs, including sibling variant directories.

The fixture explicitly sets `DisableTransitiveProjectReferences=true` for this
narrow direct-edge case. This is a fixture property and a measured scope boundary,
not an adapter policy or a proposed workaround for arbitrary upstream projects.
The separate default-transitive control removes it and preserves the failure
and nonisolated behavior described below.

| Case | Observed ordinary MSBuild behavior |
| --- | --- |
| Direct configured edges | Isolated static graph has 7 nodes / 7 edges, including traversal. Six cold CoreCompile markers: App, Left, Right, Shared/red, Shared/blue, Common/plain. App prints `red:common\|blue:common`. |
| Unchanged direct-edge build | Isolated build succeeds again and App output is unchanged. CoreCompile instrumentation can run before an up-to-date target; this is not a compiler cache-hit assertion. |
| Default SDK transitive references | Graph has 7 nodes / 17 edges. Isolated Build fails `MSB4252`: App requests Shared without Flavor, absent from the inferred configured nodes. This remains a failing isolation baseline. |
| Default SDK references, nonisolated control | Ordinary graph Build succeeds, adds a dynamic Shared/plain invocation, and App prints `red:common\|blue:common`. Success without isolation does not qualify the adapter. |
| Selected existing inner framework | `Multi.csproj` retains `TargetFrameworks=net10.0;netstandard2.1`; selecting global `TargetFramework=net10.0` builds only that inner framework with isolation. No netstandard2.1 output and no outer-build marker. |
| Unselected outer graph | Both declared framework outputs exist; each inner framework has one cold marker and the outer build reports both frameworks. This is ordinary MSBuild behavior only. |

Ordinary traversal Restore does not materialize both red/blue Shared assets in
this shape. The suite first records this absence, then explicitly restores each
Shared configuration before compilation. It does not copy one variant's restore
assets into another variant. This is additional evidence that preparation must
model restore per configuration; one project-path restore directory is insufficient.

The first cold experiment failed `NETSDK1004` for the variant assets. After
explicit variant restores, default transitive references still failed `MSB4252`.
An initial repeat build also revealed sibling `obj` generated-source inclusion
and duplicate assembly attributes; the fixture now excludes all sibling `obj`
and `bin` trees. These are fixture construction findings, not adapter fixes.

## Implementation changes required

| Boundary | Current blocker | Required change before acceptance |
| --- | --- | --- |
| Graph export | IDs already include normalized effective globals. `ValidateSupported` rejects any nonempty `TargetFrameworks`, including an explicitly selected inner build; every csproj is classified as a compilation node. | Accept a selected existing supported inner framework deliberately. Model outer nodes as evaluation/aggregation nodes if outer graphs are later supported; never compile an outer node as an inner one or retarget upstream source. |
| Preparation | `prepare_graph.py` rejects duplicate project paths and globals other than Release, assumes `obj` restore paths and standard assembly-name/output layout. | Retain configured IDs across sources, restore slices, output declarations and dependencies. Use evaluated paths instead of deriving them from project stem; validate collisions before publication. |
| Action request / runner | `GraphAction` hardcodes Release/net10.0 and keys dependency bundles by project path. Artifacts stage into one workspace using physical paths. | Carry supported normalized globals and selected framework; address bundle identity by path plus effective globals. Prove two bundles can coexist without overwriting another configuration's outputs. |
| Replay plugin | Graph bundle lookup and the current-node capture/miss decision use project path alone. Capture also hardcodes net10.0. | Match the requested configured node, including effective globals/framework, for both capture and dependency replay. Preserve exact-property rejection; do not weaken it to accept whichever same-path bundle is present. |
| Restore / package inputs | Variant assets are not produced by a single traversal restore in this fixture; current package preparation assumes one project assets path. | Select the evaluated assets path per configured node and preserve package closure independently. Agree this interface with the R02 restore work before implementation. |
| Discovery / graph edges | Existing re-evaluation compares complete manifests. Edge metadata changes can alter configured IDs, convergence and required bundles. | Add actual Bazel dependency/action evidence for red-to-blue changes and GlobalPropertiesToRemove mutations, including stale-manifest rejection. Do not hand-edit generated plans. |
| Default transitive semantics | Ordinary isolated Build rejects the inferred graph even though nonisolated Build works. | Investigate the MSBuild static/dynamic graph mismatch separately. Keep the direct-edge acceptance scope explicit until default behavior can be retained with isolation. |

For the Serilog prerequisite, the smallest next slice is selecting its existing
net10.0 inner build while retaining its multi-target source declaration. Qualify
that end to end before full outer/multi-framework execution. The ordinary Multi
fixture establishes both semantics but does not make either a supported adapter
operation. Custom Flavor support, replay property rejection, action-set changes,
relocation, configured restore and output collision controls remain separate R03
gates. Solution formats, resolver SDKs and wider frameworks remain future slices.

## Selected-inner execution implementation

The first R03 production slice permits an explicitly selected existing net10.0
inner build while retaining the source `TargetFrameworks` declaration. Unselected
outer builds and a selection absent from that declaration still fail export.
Preparation carries normalized global properties through the generated rule and
`graph_global_properties` action request; the runner passes them to MSBuild.
Replay retains its existing exact property comparison. This first slice still
requires standard output paths and one configured node per project path.

The exporter suite passed all 13 tests on native macOS ARM64, including selected
inner export and invalid-selection rejection; ActionRunner builds successfully.
Generated inner-build acceptance is a separate pending gate at this commit.

## Configured execution implementation

The next slice carries evaluated assets, output and reference directories in each
node's additive `execution` object. Preparation stages restore state per configured
ID, excludes dependency source files, and rejects overlapping configured output
folders before publication. The runner uses `graph_global_properties`,
`graph_assets_file` and `graph_output_directories`. Bundles are selected by project
path and complete global properties; property names are case-insensitive as in
MSBuild, while values and property sets must match exactly. The imposed
`IsGraphBuild=true` property is included in current-node capture identity.

Flavor graphs require an explicitly authored `DisableTransitiveProjectReferences`
setting; the adapter rejects the unsupported default-transitive case rather than
changing project semantics. Restore metadata output paths must agree with the
evaluated assets location, detecting a variant restore copied from another folder.
Supported custom output paths remain under each project's bin/obj directories.

The initial native macOS configured probe completed at
`/private/tmp/r03-configured-smoke3`: six cold project actions, no unchanged
actions, only Right and App after blue-to-red edge convergence, and six disk-cache
hits after deleting and relocating both preparation and generated workspaces.
Outputs were `red:common|blue:common` and `red:common|red:common` respectively.
Bazel pruned unrequested intermediate bundles in the all-hit case, so this first
probe does not establish full-bundle byte equality; the acceptance probe is being
updated to request every node explicitly. Linux execution remains blocked by the
repository's CI account billing gate and is not claimed.
