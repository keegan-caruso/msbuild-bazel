# Bazel-managed SDK toolchains

The migration removes host-path SDK acquisition in favor of verified downloads
and SDK artifacts produced by Bazel targets. Source-built runtime execution and
source-built SDK compilation are separate contracts.

## Step 1: remove empty runtime manifests

Removed the empty runtime-roots file from repository generation, toolchain
attributes, compilation requests and the runner. Sandbox roots still explicitly
include the SDK, runner and declared packages.

Validation on macOS ARM64: `bash scripts/check.sh`,
`bash scripts/check-dotnet.sh` and `bash scripts/check-analysis.sh` passed with
Bazel 9.2.0 and SDK 10.0.400. No GitHub CI was dispatched.

## Step 2: common SDK artifact declarations

`msbuild_sdk` in `msbuild/sdk.bzl` describes either downloaded or generated SDK
files. It creates the runner bootstrap, compilation toolchain, bundled runtime,
SDK host, and constrained registration targets. Supply `dotnet`, `files`, exact
`sdk_version`, `runtime_version`, and `runtime_identifier`; register
`<name>_registered` and `<name>_runtime_registered`.

The real dotnet executable and all SDK files/directory artifacts must share their
SDK layout beneath the executable's parent. Metadata is explicit during analysis;
SDK contents are consumed during execution. A source SDK producer must not depend
on the toolchain it is producing; bootstrap tools belong to a separate graph.

`generated_sdk.py` passed build/test, offline reuse, a body edit that reran the
failing test, and an API edit rejected by compilation on macOS ARM64/Bazel 9.2.0.
Its synthetic action repackages a pinned SDK into a generated executable and
six directory artifacts. This proves artifact handoff, not compilation of the
entire dotnet SDK from source.

## Step 3: retire host-path acquisition

Ordinary fixture and benchmark graphs now use `dotnet.sdk`; the old
`local_dotnet_sdk` repository and its tests are removed. The deliberate runner
comparison benchmark retains a custom runner with downloaded SDK labels.
`dotnet` and `files` aliases expose those declared artifacts without host paths.
Contributor bootstrap remains available for tooling and upstream preparation.

The migrated acceptance fixture passed build/run/test, body edits, declared-input
rejection and independent output-base disk-cache recovery on macOS ARM64/Bazel
9.2.0. Remote caching is a separate qualification gate below.

## Step 4: one application runtime path

Applications now require a selected runtime provider, either the SDK's registered
runtime or an explicit `runtime_host`. The legacy application SDK-file closure
and `requires_runtime_toolchain` switch are removed. The runner rejects a missing
runtime host instead of using its own process's SDK. Compilation and application
runtime selection remain separate.

Owned-code/unit suites and all 43 analysis tests passed on macOS ARM64/Bazel
9.2.0. A new negative control proves omission cannot invoke the runner's host.

Generated SDK directory artifacts are also expanded and validated against the
SDK root in the worker's startup inventory. This preserves exact per-file worker
input matching without requiring analysis-time knowledge of generated contents.
