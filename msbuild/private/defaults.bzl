"""Defaults qualified by the selected execution platform, never the target OS."""

STABLE_PATHS_TOOLCHAIN = "//msbuild:stable_paths_toolchain_type"

def _capability(_ctx):
    return [platform_common.ToolchainInfo(qualified_linux_bwrap = True)]

stable_paths_capability = rule(implementation = _capability)

def automatic(value):
    """Encode an optional boolean for rule analysis."""
    return -1 if value == None else (1 if value else 0)

def stable_paths(ctx):
    """Return the declared capability of the selected execution platform."""
    return ctx.toolchains[STABLE_PATHS_TOOLCHAIN] != None
