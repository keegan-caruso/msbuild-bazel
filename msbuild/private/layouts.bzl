"""Artifact layouts, runtime hosts and reference packs."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildLayoutInfo", "MSBuildReferencePackInfo", "MSBuildRuntimeInfo", "MSBuildToolInfo")

def _layout(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    request = ctx.actions.declare_file(ctx.label.name + ".layout.json")
    rows = []
    for target, path in ctx.attr.paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Layout paths require exactly one file or directory per label")
        rows.append({"source": files[0].path, "path": path})
    ctx.actions.write(request, json.encode({"files": rows, "output": output.path}))

    # Inspect the actual producer tree: Linux sandbox input trees contain synthetic
    # file symlinks, indistinguishable from forbidden links in a producer output.
    # Composition still reads only declared inputs and remains remotely cacheable.
    ctx.actions.run(executable = tc.dotnet, arguments = [tc.runner.path, "layout", request.path], inputs = depset([request, tc.runner] + ctx.files.paths, transitive = [tc.sdk, tc.runner_support]), outputs = [output], mnemonic = "MSBuildLayout", execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1"})
    return [DefaultInfo(files = depset([output])), MSBuildLayoutInfo(directory = output)]

msbuild_layout = rule(implementation = _layout, attrs = {"paths": attr.label_keyed_string_dict(allow_files = True)}, toolchains = [_TOOLCHAIN])

def _runtime(ctx):
    path = ctx.attr.entry_point
    if path.startswith("/") or "\\" in path or any([p in ["", ".", ".."] for p in path.split("/")]):
        fail("Runtime entry_point must be a safe relative path")
    directory = ctx.attr.layout[MSBuildLayoutInfo].directory
    return [DefaultInfo(files = depset([directory])), MSBuildRuntimeInfo(directory = directory, entry_point = path)]

msbuild_runtime = rule(implementation = _runtime, attrs = {
    "layout": attr.label(mandatory = True, providers = [MSBuildLayoutInfo]),
    "entry_point": attr.string(mandatory = True),
})

def _reference_pack(ctx):
    files = ctx.files.srcs + [dep[MSBuildAssemblyInfo].reference for dep in ctx.attr.assemblies]
    if not files or any([f.extension != "dll" or f.is_directory for f in files]):
        fail("A reference pack requires explicit assembly DLLs")
    references = depset(files, transitive = [dep[MSBuildAssemblyInfo].references for dep in ctx.attr.assemblies])
    return [DefaultInfo(files = references), MSBuildReferencePackInfo(references = references)]

msbuild_reference_pack = rule(implementation = _reference_pack, attrs = {
    "srcs": attr.label_list(allow_files = [".dll"]),
    "assemblies": attr.label_list(providers = [MSBuildAssemblyInfo]),
})

def _native_tool(ctx):
    directory = ctx.attr.layout[MSBuildLayoutInfo].directory
    return [DefaultInfo(files = depset([directory])), MSBuildToolInfo(native = True, layout_prefix = "", properties = {}, project = "native-tools/" + ctx.label.name, entry_point = ctx.attr.entry_point, directories = depset([directory]), packages = depset(), data = [], files = depset([directory]))]

msbuild_native_tool = rule(implementation = _native_tool, attrs = {
    "layout": attr.label(mandatory = True, providers = [MSBuildLayoutInfo]),
    "entry_point": attr.string(mandatory = True),
})
