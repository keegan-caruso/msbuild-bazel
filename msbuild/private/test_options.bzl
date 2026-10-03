"""Shared test protocol attributes and analysis checks."""

load(":providers.bzl", "MSBuildRuntimeInfo", "MSBuildTestToolInfo")

TEST_OPTIONS_ATTRS = {
    "test_protocol": attr.string(default = "executable", values = ["executable", "mtp", "vstest"]),
    "expected_exit_code": attr.int(default = 0, doc = "Success status for executable tests (0 through 255)."),
    "test_settings": attr.label(allow_single_file = True),
    "test_settings_output": attr.string(),
    "test_filter_argument": attr.string(values = ["", "--filter", "--filter-query"]),
    "allow_empty_tests": attr.bool(),
    "env": attr.string_dict(),
    "test_diagnostics": attr.bool(),
    "test_output_type": attr.string(default = "library", values = ["library", "exe"]),
    "test_output_dirs": attr.string_list(),
    "test_working_directory": attr.string(),
    "test_runner": attr.label(providers = [MSBuildTestToolInfo]),
    "test_adapters": attr.label_list(providers = [MSBuildTestToolInfo]),
}

def validate_test(ctx):
    """Reject unsupported or inconsistent test protocol declarations.

    Args:
        ctx: Test rule context.
    """
    if ctx.attr.expected_exit_code < 0 or ctx.attr.expected_exit_code > 255:
        fail("expected_exit_code must be between 0 and 255")
    if ctx.attr.expected_exit_code != 0 and ctx.attr.test_protocol != "executable":
        fail("expected_exit_code requires the executable test protocol")
    if ctx.attr.test_settings and ctx.attr.test_settings_output:
        fail("Declare either test_settings or test_settings_output")
    for attribute in ["test_settings_output", "test_working_directory"]:
        path = getattr(ctx.attr, attribute)
        if path and (path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")])):
            fail(attribute + " must be a safe relative path")
    if ctx.attr.shard_count > 1:
        fail("Executable tests do not yet support sharding")
    if ctx.attr.test_diagnostics and ctx.attr.test_protocol != "vstest":
        fail("test_diagnostics currently requires VSTest")
    if ctx.attr.test_protocol == "vstest":
        if ctx.attr.runtime_host and ctx.attr.runtime_host[MSBuildRuntimeInfo].launch_mode == "corerun":
            fail("VSTest requires a dotnet runtime host")
        if not ctx.attr.test_runner:
            fail("VSTest requires an explicit test_runner")
        if ctx.attr.test_filter_argument:
            fail("VSTest uses TestCaseFilter syntax; test_filter_argument is only for MTP")
    elif ctx.attr.test_runner or ctx.attr.test_adapters:
        fail("test_runner and test_adapters are only supported by VSTest")
