"""Declared test runners and adapters."""

load(":providers.bzl", "MSBuildPackageInfo", "MSBuildTestToolInfo")

def _test_tool(ctx):
    path = ctx.attr.path
    if path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")]):
        fail("Test tool path must be a safe relative path")
    package = ctx.attr.package[MSBuildPackageInfo]
    return [DefaultInfo(files = package.files), MSBuildTestToolInfo(directory = package.directory, path = path, files = package.files)]

msbuild_test_tool = rule(
    implementation = _test_tool,
    attrs = {
        "package": attr.label(mandatory = True, providers = [MSBuildPackageInfo]),
        "path": attr.string(mandatory = True),
    },
)
