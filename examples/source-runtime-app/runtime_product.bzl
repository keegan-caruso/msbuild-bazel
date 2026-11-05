"""Declared build, package and execution checks for the pinned runtime example."""

load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_binary", "msbuild_graph_test", "msbuild_runtime", "msbuild_runtime_layout")
load("@rules_pkg//pkg:tar.bzl", "pkg_tar")
load("@rules_python//python:defs.bzl", "py_test")

def source_runtime_application(name, projects, native_files, provenance):
    """Connect explicit framework projects and native artifacts to the sample app.

    Args:
        name: App target name; also prefixes its build, host and layout targets.
        projects: Configured shared-framework project keys in the graph.
        native_files: Native producer labels mapped to runtime destination paths.
        provenance: Pinned source and toolchain build facts.
    """
    runtime = name + "_source_runtime"
    host = name + "_host"
    build = name + "_build"
    files = name + "_files"
    msbuild_runtime_layout(
        name = runtime,
        graph = ":graph",
        projects = projects,
        native = native_files,
        data = {"LICENSE.TXT": "LICENSE.TXT", "THIRD-PARTY-NOTICES.TXT": "THIRD-PARTY-NOTICES.TXT"},
        version = "10.0.0",
        target_framework = "net10.0",
        target_framework_moniker = ".NETCoreApp,Version=v10.0",
        runtime_identifier = "linux-arm64",
        build_id = provenance["sourceCommit"],
        build_info = "source-runtime.json",
        provenance = json.encode(provenance),
    )
    msbuild_runtime(name = host, layout = ":" + runtime, entry_point = "dotnet", runtime_identifier = "linux-arm64", version = "10.0.0", env = {"RUNTIME_PROVIDER": "source"})
    msbuild_graph(name = build, runner = ":graph_runner", contract = "app/contract.json", source_root = "app", srcs = ["app/App.csproj", "app/Program.cs"], linux_stable_paths = True, linux_worker = True)
    msbuild_graph_binary(name = name, graph = ":" + build, assembly = "bin/Release/net10.0/App.dll", runtime_host = ":" + host)
    native.filegroup(name = files, srcs = [":" + name])
    msbuild_graph_test(name = name + "_test", graph = ":" + build, assembly = "bin/Release/net10.0/App.dll", runtime_host = ":" + host, args = ["--verify-product"])
    pkg_tar(name = "runtime_package", visibility = ["//visibility:public"], srcs = [":" + runtime], strip_prefix = runtime + ".layout", extension = "tar.gz", preserve_mode = True, stamp = 0, allow_duplicates_with_different_content = False)
    py_test(
        name = "runtime_test",
        srcs = ["runtime_product_test.py"],
        main = "runtime_product_test.py",
        args = [
            "--runtime=$(rootpath :" + runtime + ")",
            "--graph=$(rootpath :graph)",
            "--app=$(rootpath :" + files + ")",
            "--package=$(rootpath :runtime_package)",
            "--sandbox=$(rootpath //native:sandbox)",
            "--inventory=$(rootpath runtime-product.json)",
        ] + ["--native=" + path + "=$(rootpath " + label + ")" for label, path in sorted(native_files.items())],
        data = [":" + runtime, ":graph", ":" + files, ":runtime_package", "//native:sandbox", "runtime-product.json"] + native_files.keys(),
        size = "large",
        # This check creates its own filesystem/network namespace to exclude the
        # SDK. The qualified host must permit nested Bubblewrap namespaces.
        tags = ["no-sandbox", "no-remote-exec"],
        target_compatible_with = ["@platforms//os:linux", "@platforms//cpu:aarch64"],
    )
