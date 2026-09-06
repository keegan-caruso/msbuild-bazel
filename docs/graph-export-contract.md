# Configured graph export: milestone 1 contract

This contract and `tests/graph/test_export_graph.py` precede implementation.
Export is local preparation, not compilation or automatic Bazel integration.

## Process

Build `tools/GraphExport` with the pinned SDK, then invoke its `GraphExport.dll`
using that SDK's `dotnet` with `--request request.json`. The request has
`schemaVersion: 1`, absolute `workspace`, `dotnetRoot`, `packageRoot`, `output`,
`sdkVersion`, and `entryPoints` containing workspace-relative `project` paths
and `globalProperties` string maps. An omitted Configuration defaults to Release.
Restore each workspace independently before exporting. Acquisition and restore
are outside this process. The output must not already exist.

Success returns one JSON object on stdout (`ok: true`, `schemaVersion: 1`) and
atomically publishes the manifest. Failure returns nonzero, a diagnostic code
on stderr and no new manifest. Missing inputs, unsupported configurations,
unsafe paths and malformed requests are errors, never empty-success fallbacks.

## Manifest

The deterministic manifest contains `schemaVersion`, `toolchain`, `entryPoints`,
`graphInputs`, and sorted `nodes`. Each configured C# node contains its `id`,
workspace-relative `project`, sorted/case-normalized `globalProperties`,
`targetFramework`, `outputType`, direct `dependencies`, `inputs`, and `outputs`.
Node identity hashes project path plus effective global properties, not source
contents. Different configurations remain distinct even at one project path.
Traversal projects supply graph inputs and expand entry points; they are not
compilation actions. A four-project diamond must have four compilation nodes.

Inputs have `kind`, normalized `path`, and SHA-256. Boundaries cover project,
source/resource/content/additional/analyzer inputs, evaluated imports, restore
metadata, restored package files, and explicit `BazelExtraInput` declarations.
Outputs have `kind` and workspace-relative `path`; `BazelExtraOutput` can extend
that declaration. Missing generated sources must be declared separately by a
future generator contract rather than silently ignored as ordinary inputs.

Paths use logical workspace, package, SDK and adapter roots, never producer
checkout paths. Restore metadata hashes normalize known absolute roots;
ordinary source and binary payload hashes remain byte-sensitive. Equivalent
independently restored checkouts must produce identical normalized manifests.
Both lexical path escapes and symlink escapes are rejected. Subject outputs
must remain under the workspace. The SDK and adapter are explicit local roots,
not evidence of full host closure or portable/remote execution identity.

## Initial support and acceptance

The initial scope is trusted SDK-style C# net10.0 projects, Release or Debug,
portable managed assets, and Microsoft.Build.Traversal 4.1.82. Multi-targeting,
RIDs, specialized SDKs and undeclared arbitrary target behavior are unsupported.
ProjectGraph discovers configured nodes. Custom export targets collect the
input/output declarations without requesting Build, Restore or CoreCompile.
MSBuild project evaluation is trusted code, not a security sandbox.

Acceptance covers the diamond and its direct edges; configuration identity;
relocation equality; source digest changes; input/output declarations; explicit
custom inputs; no subject compilation; missing sources/restore; lexical and
symlink escapes; and rejection of multi-targeting and RIDs. Existing two-project
controls remain unchanged. Run `python3 -m unittest discover -s tests/graph -v`.

## Evidence

The first test commit intentionally fails because the exporter does not exist.
Record the red CI run before implementation, then append measured commands,
results and remaining limitations. No passing results are claimed here.
