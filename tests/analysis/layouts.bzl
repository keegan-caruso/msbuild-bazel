"""Layout, runtime and explicit reference-pack contracts."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "MSBuildLayoutInfo", "MSBuildReferencePackInfo", "MSBuildRuntimeInfo", "msbuild_layout", "msbuild_reference_pack", "msbuild_runtime")
load(":helpers.bzl", "action", "failure_test", "paths", "request")

def _layout(env, targets):
    layout = targets.layout[MSBuildLayoutInfo].directory
    env.expect.that_file(targets.runtime[MSBuildRuntimeInfo].directory).equals(layout)
    env.expect.that_str(targets.runtime[MSBuildRuntimeInfo].entry_point).equals("dotnet")
    env.expect.that_collection(paths(action(targets.layout, "MSBuildLayout").inputs)).contains("tests/analysis/dotnet")
    env.expect.that_str(request(targets.layout, ".layout.json")["files"][0]["path"]).equals("dotnet")
    env.expect.that_collection(targets.pack[MSBuildReferencePackInfo].references.to_list()).contains(targets.leaf[MSBuildAssemblyInfo].reference)

def layout_tests(name):
    """Declare layouts tests.

    Args:
        name: Prefix for test names.
    """
    msbuild_layout(name = "layout", paths = {"dotnet": "dotnet"}, tags = ["manual"])
    msbuild_runtime(name = "runtime", layout = ":layout", entry_point = "dotnet", tags = ["manual"])
    msbuild_reference_pack(name = "pack", assemblies = [":leaf"], tags = ["manual"])
    analysis_test(name = name + "_contracts", targets = {n: ":" + n for n in ["layout", "runtime", "pack", "leaf"]}, impl = _layout)
    msbuild_runtime(name = "unsafe_runtime", layout = ":layout", entry_point = "../dotnet", tags = ["manual"])
    failure_test(name + "_escape", ":unsafe_runtime", "Runtime entry_point must be a safe relative path")
    msbuild_reference_pack(name = "empty_pack", tags = ["manual"])
    failure_test(name + "_empty_pack", ":empty_pack", "A reference pack requires explicit assembly DLLs")
