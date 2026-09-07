# Exported graph execution: milestone 2

This contract and executable acceptance precede implementation. Local preparation
consumes a schema 1 graph manifest and its independently restored workspace:
`python3 tools/prepare_graph.py --workspace PATH --manifest FILE --output DIR`.
The output directory must be new. It contains one Bazel `node_<id>` target per
configured node and `//:all` for the exported entry points. Edges retain direct
dependencies; transitive bundles provide graph evaluation and replay inputs.

The first execution slice supports the exported net10.0 Release managed diamond,
with standard SDK output layouts and no package references. Other configurations
or output layouts fail explicitly. Sources belong to their owning compilation
action; referenced projects and imports remain available for graph evaluation.
Restore/tool acquisition remain preparation. Actions retain native sandbox,
network blocking and no-remote requirements.

Every action compiles only its own project, replays all reachable dependencies,
and exports its own artifacts plus versioned result metadata. Consumers verify
artifact hashes before staging. Payload identity includes project, SDK, framework
and global properties. Shared dependencies have a single Bazel producer.

`python3 tools/probe_graph_execution.py --output DIR` retains a normal static-graph
baseline, the generated workspace, execution logs, bundles and report.json.
The report contains `schemaVersion`, `baselineOutput`, `output`, `nodes` (id to
project), `executedProjects`, and `actions` keyed by project with `compiledProjects`
and `replayHits`. Acceptance requires four native sandbox executions, exactly one
compilation per action, Shared compiled once, complete diamond replay and baseline
behavior parity. This does not prove general NuGet, remote execution or host closure.

## First-slice preparation checks

The only accepted global-property map is `configuration=Release`. Preparation
rejects Debug, additional properties, package libraries, nonstandard/extra outputs,
duplicate project paths, missing dependency nodes, cycles, path escapes, stale
exported input hashes and declared source inputs under obj. The version-1 toolchain
contract is checked. Exported workspace, SDK and adapter files participate in
preparation verification; source/import/restore state is then staged per action.
Restore JSON root normalization follows the exporter, including NuGet's derived
dgspec hash. The full graph JSON is diagnostic preparation output, not a shared
input to every compilation action.

Graph wrappers preserve nearest optional Directory.Build.props/targets imports;
the original two-project wrappers are unchanged. `--root-project` on the probe
checks a root-level csproj without either Directory.Build file. This slice assumes
standard bin/Release/net10.0 output and reference-assembly locations. Full configured
graph execution, including Debug and package nodes, remains later work.

Schema-1 `entryRequests` persists canonical discovery requests: project paths are
workspace-relative with redundant path segments removed, property keys have stable
ordering, and requests are sorted by project and their property map. The
exporter-forced `BazelGraphExport`, `CustomAfterMicrosoftCommonTargets` and
`RestorePackagesPath` values are omitted case-insensitively because evaluation
always replaces them. Other entry properties retain their spelling and values;
they must remain available when preparation re-evaluates discovery. Equivalent
caller entry order, path spelling, property order and ignored forced-property
values must not change the exported manifest.
