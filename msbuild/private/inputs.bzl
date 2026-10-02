"""Complete build tool layouts and declared MSBuild task bindings."""

load(":providers.bzl", "MSBuildBindingInfo", "MSBuildLayoutInfo", "MSBuildToolInfo")

def _tool(ctx):
    entry = ctx.attr.entry_point
    if entry.startswith("/") or "\\" in entry or any([part in ["", ".", ".."] for part in entry.split("/")]):
        fail("Tool entry_point must be a safe relative file path")
    directory = ctx.attr.layout[MSBuildLayoutInfo].directory
    files = depset([directory])
    return [DefaultInfo(files = files), MSBuildToolInfo(directory = directory, entry_point = entry, files = files)]

msbuild_tool = rule(
    implementation = _tool,
    attrs = {
        "layout": attr.label(mandatory = True, providers = [MSBuildLayoutInfo], cfg = "exec"),
        "entry_point": attr.string(mandatory = True),
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
