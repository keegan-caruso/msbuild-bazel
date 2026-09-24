"""Declared items, project outputs and build tool bindings."""

load(":paths.bzl", _file = "input_file")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildBindingInfo", "MSBuildItemsInfo", "MSBuildProjectOutputInfo", "MSBuildToolInfo")

def _project_output(ctx):
    assembly = ctx.attr.assembly[MSBuildAssemblyInfo]
    return [DefaultInfo(files = depset([assembly.reference if ctx.attr.artifact == "reference" else assembly.runtime])), MSBuildProjectOutputInfo(assembly = assembly, item_type = ctx.attr.item_type, metadata = ctx.attr.metadata, artifact = ctx.attr.artifact)]

msbuild_project_output = rule(
    implementation = _project_output,
    attrs = {
        "assembly": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo]),
        "item_type": attr.string(mandatory = True),
        "artifact": attr.string(default = "implementation", values = ["implementation", "reference"]),
        "metadata": attr.string_dict(),
    },
)

def _tool(ctx):
    info = ctx.attr.assembly[MSBuildAssemblyInfo]
    entry = ctx.attr.entry_point or info.reference.basename
    if entry.startswith("/") or "\\" in entry or any([part in ["", ".", ".."] for part in entry.split("/")]):
        fail("Tool entry_point must be a safe relative file path")
    prefix = ctx.attr.layout_prefix
    if prefix and (prefix.startswith("/") or "\\" in prefix or any([part in ["", ".", ".."] for part in prefix.split("/")])):
        fail("Tool layout_prefix must be a safe relative path")
    if prefix:
        entry = prefix + "/" + entry
    directories = depset([info.runtime], transitive = [info.runtimes])
    data = info.runtime_data.to_list()
    files = depset([row.file for row in data], transitive = [directories, depset([row.directory for row in info.runtime_packages.to_list()])])
    return [DefaultInfo(files = files), MSBuildToolInfo(native = False, layout_prefix = prefix, properties = dict(info.properties, Configuration = info.configuration, TargetFramework = info.framework), project = info.project, entry_point = entry, directories = directories, packages = info.runtime_packages, data = data, files = files)]

msbuild_tool = rule(
    implementation = _tool,
    attrs = {
        "assembly": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo], cfg = "exec"),
        "entry_point": attr.string(),
        "layout_prefix": attr.string(),
    },
)

def _binding(ctx):
    tool = ctx.attr.tool[MSBuildToolInfo]
    return [DefaultInfo(files = tool.files), MSBuildBindingInfo(tool = tool, property_name = ctx.attr.property_name)]

msbuild_file_binding = rule(
    implementation = _binding,
    attrs = {
        "tool": attr.label(mandatory = True, providers = [MSBuildToolInfo]),
        "property_name": attr.string(mandatory = True),
    },
)

def _items(ctx):
    rows = [{"type": ctx.attr.item_type, "file": _file(file), "metadata": ctx.attr.metadata} for file in ctx.files.srcs]
    return [DefaultInfo(files = depset(ctx.files.srcs)), MSBuildItemsInfo(items = rows, files = depset(ctx.files.srcs), target_items = [])]

msbuild_items = rule(
    implementation = _items,
    attrs = {
        "item_type": attr.string(mandatory = True),
        "srcs": attr.label_list(allow_files = True),
        "metadata": attr.string_dict(),
    },
)

def _target_items(ctx):
    files = []
    rows = []
    for dep in ctx.attr.deps:
        info = dep[MSBuildAssemblyInfo]
        if ctx.attr.target not in info.export_targets:
            fail("MSBuild target is not exported: " + ctx.attr.target)
        files.append(info.target_output)
        rows.append({"file": info.target_output.path, "target": ctx.attr.target, "type": ctx.attr.item_type, "beforeTargets": ctx.attr.before_targets})
    return [DefaultInfo(files = depset(files)), MSBuildItemsInfo(items = [], files = depset(files), target_items = rows)]

msbuild_target_items = rule(
    implementation = _target_items,
    attrs = {
        "deps": attr.label_list(providers = [MSBuildAssemblyInfo]),
        "target": attr.string(mandatory = True),
        "item_type": attr.string(mandatory = True),
        "before_targets": attr.string_list(),
    },
)
