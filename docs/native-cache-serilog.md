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

## Step 3: upstream acceptance harness

Run on the pinned macOS ARM64 Nix environment with an existing checkout at
`49b5339ce85385dc52d4d8e8f2b8308becf23506` and an acquired package cache:

```sh
python3 tools/probe_native_serilog.py --source /path/to/serilog \
  --packages /path/to/packages --output /private/tmp/native-serilog
```

The harness archives that revision, independently restores/exports/prepares the
producer and consumer, declares verified inputs and fetched seeds to native Bazel
sandbox actions, and publishes project bundles only after successful builds.
It checks that no action contacts the HTTP project-cache endpoint. Runtime
comparisons use ordinary MSBuild with the same PathMap; the upstream approval
Fact runs through VSTest with explicit source/golden data. This is a Bazel build
acceptance harness followed by controlled VSTest execution, not a new `bazel test`
rule. Per-case logs, execution provenance, runtime hashes, TRX and HTTP events are
retained under the requested output directory.

### Scope and limitations

This remains opt-in and limited to the evaluated Release/net10.0 policy and the
existing verified-package boundary. It preserves upstream project and package
files. Dependency implementation changes conservatively rebuild consumers;
reference-only generator invalidation is not claimed. Complete per-project bin
bundles duplicate some runtime/package files, favoring correctness over size.

Ordinary MSBuild produces one additional absolute-path code-coverage diagnostic,
`.msCoverageSourceRootsMapping_Serilog.ApprovalTests`. Static-graph execution does
not request the package's extra source-map target. The harness records this exact
raw-only diagnostic separately and compares all remaining runtime files without
normalizing their bytes. Code-coverage execution is not qualified.

Remote evidence uses an owned loopback HTTP server and explicit immutable
catalogs on one machine with the same SDK. It does not qualify authenticated
production caches, cross-host/SDK relocation, remote execution, arbitrary NuGet
build targets, or broad multi-targeting. The existing macOS sandbox limitations
(absolute reads and loopback access) still apply. Preparation still invokes the
existing exporter/verifier; this work establishes correctness, not a new
end-to-end performance claim.

### Measured result

The full harness passed on macOS ARM64/Nix with SDK 10.0.400. Its ten successful
build actions all executed in `darwin-sandbox`; every action had a unique nonce
to force project-cache evaluation rather than an outer Bazel action hit.

| Case | Compilations | Project hits |
| --- | ---: | ---: |
| Cold approval graph | 2 | 0 |
| Independently prepared, producer-absent HTTP recovery | 0 | 2 |
| Standalone library cold | 1 | 0 |
| Standalone library recovery | 0 | 1 |
| Test implementation edit | 1 | 1 |
| Library implementation edit | 2 | 0 |
| Library public API edit | 2 | 0 |
| PolySharp 1.15.0 to 1.16.0 | 2 | 0 |
| Corrupt library cache blob | 1 | 1 |
| Missing library cache blob | 1 | 1 |

The 142-file approval runtime matched raw MSBuild in the baseline, body-edit,
API-edit and generator-edit cases, subject only to the documented raw-only
coverage diagnostic. Recovery and both damaged-cache fallbacks matched baseline
bytes. The standalone library output also matched raw MSBuild. VSTest passed the
real approval Fact on cold, recovered, body-edited and generator-upgraded outputs;
golden mismatch, API change and an intentional test exception each executed and
failed the same Fact as expected. No tests were skipped.

Stale source and package archive bytes failed preparation without publishing a
plan. A compiler error failed the native action and left the HTTP cache unchanged.
No build action made HTTP project-cache requests. The producer source, prepared
plan, copied output, Bazel workspace and local Bazel output base were deleted
before recovery. The immutable catalog and verified HTTP blobs were sufficient.

Validation also passed the 23 native-cache unit tests and the four-node existing
synthetic cold/relocation/body-edit regression, all owned .NET formatting/warnings
checks, and the shared action-runner contract/process tests. Use a canonical `TMPDIR` such as
`/private/tmp` for the Python tests on macOS; the `/var` alias otherwise trips two
existing fixture path checks. Initial acceptance attempts exposed the coverage
sidecar comparison and read-only Bazel output cleanup; the final full run includes
both corrections.
