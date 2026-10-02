"""Qualification-only CMake bootstrap with a declared Linux filesystem."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildAssemblyInfo", "MSBuildLayoutInfo", "msbuild_graph", "msbuild_graph_layout", "msbuild_graph_runner")

_TOOLCHAIN = "@rules_msbuild//msbuild:toolchain_type"

def _native_runtime(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    if MSBuildLayoutInfo in ctx.attr.driver:
        runtime = ctx.attr.driver[MSBuildLayoutInfo].directory
        assembly = ctx.attr.driver_assembly
    else:
        driver = ctx.attr.driver[MSBuildAssemblyInfo]
        runtime = driver.runtime
        assembly = driver.assembly
    if not assembly or "/" in assembly or "\\" in assembly or assembly in [".", ".."]:
        fail("Native driver assembly must be a file stem")
    names = ["runtime.tar"] + ctx.attr.products.values()
    if not ctx.attr.products or len(names) != len({name: True for name in names}) or any(["/" in name or name in ["", ".", ".."] for name in names]):
        fail("Native product names must be unique file names")
    outputs = [ctx.actions.declare_file(ctx.label.name + ".generated/" + name) for name in names]
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [runtime.path + "/" + assembly + ".dll", ctx.file.sandbox.path, ctx.file.toolchain_archive.path, ctx.file.source_archive.path, "/source/build-native.sh"] + [file.path for file in outputs],
        inputs = depset([runtime, ctx.file.sandbox, ctx.file.toolchain_archive, ctx.file.source_archive], transitive = [tc.runtime]),
        outputs = outputs,
        mnemonic = "RuntimeNative",
        # The driver creates its own filesystem/network namespace. A second
        # Bazel namespace may prevent creation of the required user namespace.
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1", "block-network": "1"},
        env = {"LANG": "C.UTF-8"},
    )
    groups = {group: depset([outputs[i + 1]]) for i, group in enumerate(ctx.attr.products)}
    return [DefaultInfo(files = depset(outputs)), OutputGroupInfo(**groups)]

native_runtime = rule(
    implementation = _native_runtime,
    attrs = {
        "products": attr.string_dict(default = {"coreclr": "libcoreclr.so", "jit": "libclrjit.so", "host": "corerun"}),
        "driver_assembly": attr.string(default = "Task"),
        "driver": attr.label(providers = [[MSBuildAssemblyInfo], [MSBuildLayoutInfo]], cfg = "exec", mandatory = True),
        "sandbox": attr.label(allow_single_file = True, mandatory = True),
        "toolchain_archive": attr.label(allow_single_file = True, mandatory = True),
        "source_archive": attr.label(allow_single_file = True, mandatory = True),
    },
    toolchains = [_TOOLCHAIN],
)

def native_graph_driver(name):
    """Compile the SDK-only driver in an isolated declared graph workspace."""
    msbuild_graph_runner(name = name + "_runner")
    msbuild_graph(
        name = name + "_build",
        runner = ":" + name + "_runner",
        contract = "driver-contract.json",
        source_root = native.package_name(),
        srcs = ["Task.csproj", "NativeBuild.cs"],
        project_outputs = {"Task.csproj|net10.0": ["bin/Release/net10.0", "Task.dll", "Exe"]},
        linux_stable_paths = True,
        linux_worker = True,
    )
    msbuild_graph_layout(name = name, graph = ":" + name + "_build", project = "Task.csproj", framework = "net10.0")
