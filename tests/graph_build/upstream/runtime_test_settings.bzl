"""Add a reviewed slice filter to the actual SDK-generated test settings."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildLayoutInfo")

_TOOLCHAIN = "@rules_msbuild//msbuild:toolchain_type"

def _settings(ctx):
    sdk = ctx.toolchains[_TOOLCHAIN]
    tool = ctx.attr.tool[MSBuildLayoutInfo].directory
    layout = ctx.attr.layout[MSBuildLayoutInfo].directory
    output = ctx.actions.declare_file(ctx.label.name + ".runsettings")
    ctx.actions.run(
        executable = sdk.dotnet,
        arguments = [tool.path + "/Settings.dll", layout.path + "/.runsettings", ctx.attr.filter, output.path],
        inputs = depset([tool, layout], transitive = [sdk.runtime]),
        tools = [sdk.dotnet],
        outputs = [output],
        mnemonic = "RuntimeTestSettings",
    )
    return [DefaultInfo(files = depset([output]))]

runtime_test_settings = rule(
    implementation = _settings,
    attrs = {
        "tool": attr.label(providers = [MSBuildLayoutInfo], cfg = "exec", mandatory = True),
        "layout": attr.label(providers = [MSBuildLayoutInfo], mandatory = True),
        "filter": attr.string(mandatory = True),
    },
    toolchains = [_TOOLCHAIN],
)
