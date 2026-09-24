"""Layout, runtime and explicit reference-pack contracts."""

load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("//msbuild:defs.bzl", "MSBuildAssemblyInfo", "MSBuildLayoutInfo", "MSBuildReferencePackInfo", "MSBuildRuntimeInfo", "msbuild_layout", "msbuild_reference_pack", "msbuild_runtime", "msbuild_test")
load(":helpers.bzl", "action", "failure_test", "paths", "request")

def _layout(env, targets):
    layout = targets.layout[MSBuildLayoutInfo].directory
    env.expect.that_file(targets.runtime[MSBuildRuntimeInfo].directory).equals(layout)
    env.expect.that_str(targets.runtime[MSBuildRuntimeInfo].entry_point).equals("dotnet")
    env.expect.that_collection(paths(action(targets.layout, "MSBuildLayout").inputs)).contains("tests/analysis/dotnet")
    env.expect.that_str(request(targets.layout, ".layout.json")["output"]).equals(layout.path)
    env.expect.that_collection(targets.pack[MSBuildReferencePackInfo].references.to_list()).contains(targets.leaf[MSBuildAssemblyInfo].reference)

def _runtime_launch(env, targets):
    host = targets.host[MSBuildRuntimeInfo]
    env.expect.that_str(host.launch_mode).equals("corerun")
    env.expect.that_str(host.version).equals("10.0.0")
    env.expect.that_dict(host.environment).contains_exactly({"RUNTIME_TEST": "yes"})
    env.expect.that_collection(action(targets.app, "MSBuildAssembly").inputs.to_list()).not_contains(host.directory)
    env.expect.that_collection(targets.app[DefaultInfo].default_runfiles.files.to_list()).contains_at_least(host.files.to_list())
    launch = request(targets.app, ".launch.json")["runtimeHost"]
    env.expect.that_str(launch["launchMode"]).equals("corerun")
    env.expect.that_str(launch["version"]).equals("10.0.0")

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
    msbuild_runtime(name = "corehost", layout = ":layout", entry_point = "dotnet", launch_mode = "corerun", version = "10.0.0", env = {"RUNTIME_TEST": "yes"}, data = ["payload.txt"], tags = ["manual"])
    msbuild_test(name = "corehost_test", project = "Tests.csproj", target_framework = "net10.0", runtime_host = ":corehost", tags = ["manual"])
    analysis_test(name = name + "_runtime_launch", targets = {"host": ":corehost", "app": ":corehost_test"}, impl = _runtime_launch)
    msbuild_runtime(name = "reserved_host", layout = ":layout", entry_point = "dotnet", env = {"CORE_ROOT": "/ambient"}, tags = ["manual"])
    failure_test(name + "_reserved_environment", ":reserved_host", "Reserved or invalid runtime environment")
    msbuild_test(name = "corerun_vstest", project = "Tests.csproj", target_framework = "net10.0", runtime_host = ":corehost", test_protocol = "vstest", tags = ["manual"])
    failure_test(name + "_corerun_vstest", ":corerun_vstest", "VSTest requires a dotnet runtime host")
