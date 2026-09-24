"""Artifact layouts, runtime hosts and reference packs."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildLayoutInfo", "MSBuildReferencePackInfo", "MSBuildRuntimeInfo", "MSBuildToolInfo")

def _add_layout_input(args, source, destination):
    # Expand only Bazel-declared tree children, not a filesystem walk through
    # sandbox links. Capture just the destination string in this callback.
    def entries(file, expander):
        if not file.is_directory:
            return [json.encode({"source": file.path, "path": destination})]
        prefix = "" if destination == "." else destination + "/"
        return [json.encode({"source": "", "path": destination, "directory": True})] + [
            json.encode({"source": child.path, "path": prefix + child.path[len(file.path) + 1:]})
            for child in expander.expand(file)
        ]

    args.add_all([source], map_each = entries, expand_directories = False, allow_closure = True)

def _layout(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    request = ctx.actions.declare_file(ctx.label.name + ".layout.json")
    args = ctx.actions.args()
    args.use_param_file("@%s", use_always = True)
    args.set_param_file_format("multiline")
    for target, path in ctx.attr.paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Layout paths require exactly one file or directory per label")
        _add_layout_input(args, files[0], path)
    ctx.actions.write(request, json.encode({"output": output.path}))

    ctx.actions.run(executable = tc.dotnet, arguments = [tc.runner.path, "layout", request.path, args], inputs = depset([request, tc.runner] + ctx.files.paths, transitive = [tc.runtime, tc.runner_support]), outputs = [output], mnemonic = "MSBuildLayout")
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
