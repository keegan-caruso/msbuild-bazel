# Native-cache Serilog qualification

## Step 1: evaluated inputs

`tools/native_graph.py` adds an opt-in input path through the existing
`prepare_graph.prepare` boundary. It re-evaluates the exported graph, verifies
source/restore digests, and stages packages through the existing archive/payload
manifest checks. Native session identities include exact authored bytes,
normalized Build restore inputs, selected package manifests, evaluated SDK/import
inputs and configuration. Publication of the input plan is atomic.

The admitted configuration is one graph entry, one configuration per project,
Release/net10.0 and ordinary nested project output layouts. The synthetic
qualifier remains unchanged. The new input policy is `evaluated-packages-v1`;
execution support and upstream acceptance are separate subsequent steps.

Step 1 validation: 23 native-cache unit tests passed. A freshly restored and
exported pinned Serilog approval-test graph produced a two-node native input plan
with its verified package payloads. Changing `src/Serilog/Log.cs` after export was
rejected as a stale manifest, and no output plan was published. Acquisition-only
NuGet metadata contributes its verified export digest to identity; staged Build
payloads follow the existing package-manifest boundary.
