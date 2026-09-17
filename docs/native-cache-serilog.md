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

## Step 2: package-aware execution

The runner imports authored `Directory.Build.targets` and selects the declared
net10.0 inner builds using the same late SDK framework-selection technique as the
existing graph adapter. The plugin still verifies the evaluated graph against the
session. Package-policy bundles contain the complete project `bin/Release/net10.0`
output plus its reference assembly; SDK-generated dependency/runtime metadata is
preserved. Downstream keys hash the complete dependency artifact manifest, so
implementation changes conservatively invalidate consumers and generators.
The package-free policy retains reference-assembly keys and runtime composition.

Direct cold execution of the pinned Serilog approval graph compiled two projects.
A fresh runner workspace restored both with zero compilation. All 142 runtime
files were byte-identical, and VSTest executed the real upstream approval Fact
(one passed, none skipped) against the recovered output. The native project builds
with warnings as errors and passes whitespace formatting. The existing four-node
synthetic Bazel regression covers cold, relocated recovery and body edits.
