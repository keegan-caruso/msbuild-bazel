"""Toolchain declarations for downloaded or Bazel-produced SDK artifacts."""

load("//msbuild:toolchain.bzl", "msbuild_toolchain")
load("//msbuild/private:sdk_bootstrap.bzl", "sdk_runner", "sdk_runtime", "sdk_runtime_toolchain")

_PLATFORMS = {
    "linux-arm64": ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    "linux-x64": ["@platforms//os:linux", "@platforms//cpu:x86_64"],
    "osx-arm64": ["@platforms//os:osx", "@platforms//cpu:aarch64"],
    "osx-x64": ["@platforms//os:osx", "@platforms//cpu:x86_64"],
}

def msbuild_sdk(name, dotnet, files, sdk_version, runtime_version, runtime_identifier, visibility = None):
    """Describe a complete SDK rooted beside its declared dotnet executable.

    Args:
        name: Target prefix. Register <name>_registered and <name>_runtime_registered.
        dotnet: Label of the real dotnet executable, not a shell launcher.
        files: Labels containing the complete SDK. Files or directory artifacts
            must preserve the SDK layout beneath dotnet's parent directory.
        sdk_version: Exact SDK version available beneath sdk/.
        runtime_version: Bundled runtime version.
        runtime_identifier: SDK execution platform (and bundled runtime platform).
        visibility: Visibility of the generated targets.
    """
    if runtime_identifier not in _PLATFORMS:
        fail("Unsupported SDK platform: " + runtime_identifier)
    if not sdk_version or not runtime_version:
        fail("SDK and runtime versions must be explicit")
    common = {"visibility": visibility} if visibility != None else {}
    native.filegroup(name = name + "_files", srcs = files, **common)
    sdk_runner(
        name = name + "_runner_payload",
        dotnet = dotnet,
        sdk = ":" + name + "_files",
        project = Label("//tools/ArtifactTools:ArtifactTools.csproj"),
        sources = Label("//tools/ArtifactTools:sources"),
        **common
    )
    native.filegroup(name = name + "_runner", srcs = [":" + name + "_runner_payload"], output_group = "runner", **common)
    msbuild_toolchain(
        name = name + "_toolchain",
        dotnet = dotnet,
        sdk = ":" + name + "_files",
        runner = ":" + name + "_runner",
        runner_support = [":" + name + "_runner_payload"],
        sdk_version = sdk_version,
        **common
    )
    sdk_runtime(name = name + "_runtime", dotnet = dotnet, files = ":" + name + "_files", runtime_identifier = runtime_identifier, version = runtime_version, runtime_only = True, **common)
    sdk_runtime(name = name + "_host", dotnet = dotnet, files = ":" + name + "_files", runtime_identifier = runtime_identifier, version = runtime_version, **common)
    sdk_runtime_toolchain(name = name + "_runtime_toolchain", runtime = ":" + name + "_runtime", **common)
    native.toolchain(name = name + "_registered", toolchain = ":" + name + "_toolchain", toolchain_type = Label("//msbuild:toolchain_type"), exec_compatible_with = [Label(value) for value in _PLATFORMS[runtime_identifier]], **common)
    native.toolchain(name = name + "_runtime_registered", toolchain = ":" + name + "_runtime_toolchain", toolchain_type = Label("//msbuild:runtime_toolchain_type"), target_compatible_with = [Label(value) for value in _PLATFORMS[runtime_identifier]], **common)
