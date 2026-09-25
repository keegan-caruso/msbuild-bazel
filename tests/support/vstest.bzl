"""Shared runner/adapter declarations for qualification fixtures."""

load("//msbuild:defs.bzl", "msbuild_test_tool")

def vstest_tools(name, runner_package, runner_path, adapters, visibility = None):
    """Declare one runner and explicitly versioned adapter bindings.

    Args:
        name: Prefix for generated targets, name_runner and name_ADAPTER.
        runner_package: Locked runner package target.
        runner_path: Exact executable path inside that package.
        adapters: Name to dictionary containing package and path.
        visibility: Visibility shared by the declared tools.
    """
    msbuild_test_tool(name = name + "_runner", package = runner_package, path = runner_path, visibility = visibility)
    for adapter, binding in adapters.items():
        msbuild_test_tool(name = name + "_" + adapter, package = binding["package"], path = binding["path"], visibility = visibility)
