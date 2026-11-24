# Quick start

Two SDK options for one app graph (app, library, executable test; no NuGet packages): download a pinned SDK, or consume a complete Bazel source-built SDK. Requires Bazelisk and OS .NET prerequisites. For Razor, HTTP, published assets, and declared NuGet packages, see [catalog-web](../catalog-web/README.md).

## Downloaded SDK

Copy beside a pinned rules checkout (adjust `local_path_override` if needed):

```sh
cp -R msbuild-bazel/examples/quickstart my-app
cd my-app
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

Prints `Hello from MSBuild and Bazel` using a Bazel-supplied SDK (no host SDK required). [global.json](global.json) pins 11.0.100 with roll-forward disabled; [MODULE.bazel](MODULE.bazel) selects it:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "dotnet", global_json = "//:global.json")
use_repo(dotnet, "dotnet")
register_toolchains("@dotnet//:all")
```

First build resolves release metadata and writes SDK URLs/hashes to `MODULE.bazel.lock` (commit it); later builds reuse and hash-verify those archives. To change SDK versions: edit `global.json`, rerun sync, and commit the updated lockfile and graph. Adapters follow the selected SDK's bundled framework/MSBuild (no SDK-version registration needed). Build servers can enforce locks with `--lockfile_mode=error`. See [SDK configuration](../../docs/api.md#sdks). With a roll-forward policy, `bazel run @dotnet//:update -- --sync //:sync` refreshes SDK selection and graph (review/commit diff). Optional [declared runtimes](../../docs/api.md#runtimes) select the app/test host independently.

Web/Razor apps use the same SDK declaration (bundled ASP.NET provides the default host). To run framework-dependent published outputs:

```starlark
app_graph(name = "published", target = "Publish")
msbuild_graph_binary(name = "published_app", graph = ":published", project = "App/App.csproj")
```

Run `bazel run //:published_app`; the macro supplies the publish directory and declared assets (resync after project/input changes).

[BUILD.bazel](BUILD.bazel) declares sync and uses the committed generated macro:

```starlark
load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary", "msbuild_graph_test")
load(":graph.generated.bzl", "app_graph")

msbuild_sync(name = "sync", projects = ["App/App.csproj", "Tests/Tests.csproj"])
app_graph(name = "graph")
msbuild_graph_binary(name = "app", graph = ":graph", project = "App/App.csproj")
msbuild_graph_test(name = "tests", graph = ":graph", project = "Tests/Tests.csproj")
```

New apps: declare only `msbuild_sync`, run it, add the generated load and build/run/test targets, and commit both generated files. Method-body edits build normally; resync after project/import, source-list, package, or configuration changes. `--check` verifies declarations on build servers.

## Source-built SDK

For building SDK 11.0.100 and its runtime from the signed VMR release on Linux ARM64, see the [VMR producer recipe](../../tests/source_sdk/LINUX_ARM64_11.md).

Use `msbuild_sdk` when your workspace has an SDK source producer. The upstream [component producer](../../tests/source_sdk/component_graph_prepare.py) is qualification tooling with pinned source/bootstrap/native inputs—not a general SDK source-build macro. This section shows the handoff, not a standalone SDK build recipe. Run on Linux ARM64 (values below match source-built SDK 10.0.100); for native Ubuntu 26.04 x64, see the [x64 recipe](../../tests/source_sdk/LINUX_X64.md).

**1. Separate bootstrap and application SDKs.** Keep the rules dep/override from above; replace SDK registration with:

```starlark
dotnet = use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.sdk(name = "bootstrap", version = "10.0.400", platforms = ["linux-arm64"])
use_repo(dotnet, "bootstrap")
register_toolchains("//sdk:source_registered", "//sdk:source_runtime_registered")
```

The producer uses `@bootstrap//:sdk_host` directly (or an independent bootstrap toolchain), keeping it independent of its own outputs; upstream builds may also need separately pinned bootstrap artifacts. App compilation and default execution use the registered source SDK.

**2. Describe the produced layout.** In `sdk/BUILD.bazel`, wrap `:build`, which must export `sdk_layout` (complete layout) and `dotnet` (real executable) output groups:

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

Retain the full layout beside `dotnet` (`host/`, `shared/`, `sdk/`, packs, and required SDK components; Razor consumers need the produced StaticWebAssets SDK). Archives need a declared extraction step; host SDK directories are unsupported. Match versions/platform to your producer.

**3. Sync and run.** Set `sdk.version` in `global.json` to `10.0.100` and `TargetFramework` to `net10.0` in App, Library, and Tests (pinned SDK 10.0.100 cannot compile `net11.0`). Keep the `BUILD` targets above and run:

```sh
bazel run //:sync
bazel run //:app
bazel test //:tests
bazel run //:sync -- --check
```

First source build is substantial; Bazel caches its declared outputs. For a separately source-built execution runtime with either SDK, see [source runtime app](../source-runtime-app/README.md). The repo's component experiment runs the preparation driver with `--through sdk --sdk-consumer`, then tests `//:smoke` (`--help` lists prepared source, evaluated graph, and native archive inputs).

## Incremental reuse

This example shows action caching; project reuse in changed graphs needs a qualified Linux worker or HTTP project cache ([cache setup](../../docs/api.md#caching-and-workers)). Closed package inventories or complete sync `srcs` automatically capture SDK compiler/copy selections during a private sync Build; custom task reads still require contracts. See [API](../../docs/api.md) and [support](../../docs/support.md).
