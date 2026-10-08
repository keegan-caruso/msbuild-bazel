# Quick start

Two SDK choices, one app graph: download a pinned SDK, or consume a complete SDK
produced by a Bazel source build. Requires Bazelisk and OS .NET prerequisites.
The example contains an app, library and executable test; no NuGet packages.

## Downloaded SDK

Copy beside a pinned rules checkout; adjust `local_path_override` if needed:

```sh
cp -R msbuild-bazel/examples/quickstart my-app
cd my-app
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

The app prints `Hello from MSBuild and Bazel`. Bazel supplies the SDK; a host SDK
installation is unnecessary. [global.json](global.json) pins 10.0.400 with roll-forward
disabled. [MODULE.bazel](MODULE.bazel) selects it:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "dotnet", global_json = "//:global.json")
use_repo(dotnet, "dotnet")
register_toolchains("@dotnet//:all")
```

The first build resolves release metadata and writes SDK URLs/hashes to
`MODULE.bazel.lock`; commit it. Later builds reuse that selection and verify the
archive hashes. To change SDK versions, edit `global.json`, rerun project sync,
and commit the updated lockfile and graph. Build servers can use
`--lockfile_mode=error` to reject stale locks. See [SDK configuration](../../docs/api.md#sdks).

[BUILD.bazel](BUILD.bazel) declares sync, then uses the committed generated macro:

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
load(":graph.generated.bzl", "app_graph")

msbuild_sync(name = "sync", projects = ["App/App.csproj", "Tests/Tests.csproj"])
app_graph(name = "graph")
msbuild_graph_binary(name = "app", graph = ":graph", project = "App/App.csproj")
msbuild_graph_test(name = "tests", graph = ":graph", project = "Tests/Tests.csproj")
```

For a new app, start with only `msbuild_sync`, run it, then add the generated load
and build/run/test declarations. Commit both generated files. Change library method
bodies and build normally; rerun sync after project/import, source-list, package or
configuration changes. `--check` verifies declarations on build servers.

## Source-built SDK

Use this scenario when your workspace has an SDK source producer. The public
`msbuild_sdk` API consumes its declared outputs. The upstream
[component producer](../../tests/source_sdk/component_graph_prepare.py) is
qualification tooling, with pinned source/bootstrap/native inputs; there is no
general SDK source-build macro. This section shows the handoff, not a standalone
SDK build recipe. Run this qualified scenario on Linux ARM64; the values below
match the source-built SDK 10.0.100.

**1. Select bootstrap and application SDKs separately.** Keep the rules dependency
and override from the downloaded scenario; replace its SDK registration with:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "bootstrap", version = "10.0.400", platforms = ["linux-arm64"])
use_repo(dotnet, "bootstrap")
register_toolchains("//sdk:source_registered", "//sdk:source_runtime_registered")
```

The producer uses `@bootstrap//:sdk_host` directly (or an explicit independent
bootstrap toolchain). Application compilation and default execution use the
registered source SDK. This keeps the SDK producer independent of its own outputs.
The upstream build may also require separately pinned bootstrap artifacts.

**2. Describe the produced layout.** In `sdk/BUILD.bazel`, wrap your existing
`:build` producer. It must export `sdk_layout` (the complete layout) and `dotnet`
(the real executable) output groups, as the qualified component producer does:

```starlark
load("@rules_msbuild//msbuild:sdk.bzl", "msbuild_sdk")

filegroup(name = "layout", srcs = [":build"], output_group = "sdk_layout")
filegroup(name = "dotnet", srcs = [":build"], output_group = "dotnet")
msbuild_sdk(
    name = "source",
    dotnet = ":dotnet",
    files = [":layout"],
    sdk_version = "10.0.100",
    runtime_version = "10.0.0",
    runtime_identifier = "linux-arm64",
    visibility = ["//visibility:public"],
)
```

All SDK files/trees must retain their layout beside `dotnet`: `host/`, `shared/`,
`sdk/`, packs and any required SDK components. An archive needs a declared extraction
step. A host SDK directory is not an input. Match versions/platform to your actual
producer; source-built Razor consumers also need the produced StaticWebAssets SDK.

**3. Sync and run the same app.** Set `sdk.version` in `global.json` to `10.0.100`
to match the produced SDK. Keep the app BUILD targets above, then run:

```sh
bazel run //:sync
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

SDK production is a dependency of sync/build; a first source build is substantial.
Bazel can cache its declared outputs. To run on a separately source-built runtime
while compiling with either SDK, see [source runtime app](../source-runtime-app/README.md).
The repository's component experiment uses `--through sdk --sdk-consumer` on the
producer preparation driver, then runs its generated `//:smoke` test. The driver's
`--help` lists the prepared source, evaluated graph and native archive inputs.

## Incremental reuse

The basic example demonstrates action caching. Project reuse within changed graphs
needs a qualified Linux worker or HTTP project cache. [Cache setup](../../docs/api.md#caching-and-workers)
shows both levels. Opt-in `package_build = True, resolve_references = True` captures
complete SDK compiler/copy selections during a private sync Build; custom task reads
still need contracts. [API](../../docs/api.md) covers packages, tools and tests;
[support](../../docs/support.md) lists validated scope and limits.
