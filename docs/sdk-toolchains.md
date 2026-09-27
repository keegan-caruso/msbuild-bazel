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

## Step 5: shared ordinary fixture acquisition

`tests/fixture_sdk.py` emits the common SDK declaration and registration, limited
to the fixture's actual platform. The fixture's project and dependency BUILD
files remain authored in each test. Specialized version-selection, global.json,
remote-platform and producer tests retain their explicit SDK declarations.

Benchmark workspace generation and the shared-helper acceptance fixture passed
on macOS ARM64/Bazel 9.2.0, including build/test/edit/rejection/cache controls.

## Step 6: shared validation phases

`scripts/validation.sh common` runs version-independent checks once;
`version` runs the selected Bazel toolchain/analysis/repository checks;
`acceptance <fresh-directory>` runs real builds and cache controls. Manual CI and
`test-bazel-matrix.py` invoke these same phases. The five CI dispatch controls
passed, including fail-fast behavior and acceptance without repeated common checks.

The complete shared matrix passed on macOS ARM64 for Bazel 8.8.0 and 9.2.0:
common checks, all 43 rule-analysis tests per version, SDK/runtime repository
checks, and real build/test/edit/rejection/cache acceptance. The generated-SDK
synthetic passed on both versions. SDK-extension qualification also passed SDK
pin changes, offline reuse, explicit runtime overrides and unsupported settings.

On Linux ARM64/Bazel 9.2.0, the synthetic generated SDK passed build/test and
body/API edits through a persistent worker, exercising directory inventory
expansion. These are bounded artifact-contract tests, not whole-SDK source-build
or cross-compilation qualification. No GitHub CI was dispatched.

## Source-produced SDK usage

An SDK producer exposes the executable and complete SDK payload as labels:

```starlark
load("@rules_msbuild//msbuild:sdk.bzl", "msbuild_sdk")

msbuild_sdk(
    name = "source_sdk",
    dotnet = "//sdk:dotnet",
    files = ["//sdk:payload"],
    sdk_version = "10.0.400",
    runtime_version = "10.0.11",
    runtime_identifier = "linux-arm64",
)
```

For a declaration in `//toolchains`, register these in `MODULE.bazel`:

```starlark
register_toolchains(
    "//toolchains:source_sdk_registered",
    "//toolchains:source_sdk_runtime_registered",
)
```

The payload includes dotnet and preserves SDK-relative directories such as
`sdk/`, `host/`, `shared/` and `packs/`. The labels may identify generated files
and generated directory artifacts. Neither acquisition nor analysis reads a host
SDK path. A complete upstream SDK source producer is not implemented by this
macro; it is an integration point for that producer.

Applications can still select a separately source-built runtime with
`runtime_host`, independently of the SDK used to compile them.

## Independent HTTP-cache recovery

Linux ARM64/Bazel 9.2.0 qualification used separate containers and different
checkout/output paths. With the producer stopped, an empty consumer output base
recovered runner bootstrap, SDK runtime assembly, both managed compilations and
test results from HTTP cache. No compilation ran in the consumer. Disk caching
and consumer uploads were disabled. See [compact evidence](sdk-toolchains-evidence.json).

Reproduce with `tests/explicit_msbuild/sdk_cache_workers.py --mode seed|recover`
and `--cache <HTTP URL>` in independent environments. Use
`tests/explicit_msbuild/generated_sdk.py <fresh-directory>` for generated artifact
handoff, adding `--worker` on qualified Linux workers. The ordinary matrix is
`python3 scripts/test-bazel-matrix.py --output <fresh-directory>`.

Final review also removed obsolete host-SDK switching/rewriting in the remote
fixture. Its default now uses the existing SDK-only declaration and includes
bootstrap actions in its assertions. Declaration generation and syntax were
checked; the REAPI suite was not rerun for this migration. HTTP cache recovery
above does not substitute for remote-execution qualification.
