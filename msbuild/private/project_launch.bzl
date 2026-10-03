"""Create launchers for explicit executable and test projects."""

load(":paths.bzl", _RUNTIME_TOOLCHAIN = "RUNTIME_TOOLCHAIN", _quote = "quote", _runfile = "runfile")
load(":providers.bzl", "MSBuildRuntimeInfo", "MSBuildTestToolInfo")

def create_launcher(ctx, tc, name, runtime, runtime_data, test):
    """Return the executable provider and optional test environment.

    Args:
        ctx: Project rule context.
        tc: MSBuild toolchain.
        name: Assembly name.
        runtime: Compiled runtime output.
        runtime_data: Transitive data files.
        test: Whether to create a test launcher.

    Returns:
        The executable DefaultInfo and optional RunEnvironmentInfo providers.
    """
    test_tools = ([ctx.attr.test_runner] if ctx.attr.test_runner else []) + ctx.attr.test_adapters if test else []
    def_tool = None
    if test and ctx.attr.test_runner:
        def_tool = ctx.attr.test_runner[MSBuildTestToolInfo]
    host = ctx.attr.runtime_host[MSBuildRuntimeInfo] if ctx.attr.runtime_host else None
    if host == None and ctx.toolchains[_RUNTIME_TOOLCHAIN] != None:
        host = ctx.toolchains[_RUNTIME_TOOLCHAIN].runtime
    if host == None:
        fail("No SDK runtime matches the target platform; declare a compatible SDK platform or runtime_host")
    launch_request = ctx.actions.declare_file(ctx.label.name + ".launch.json")
    ctx.actions.write(launch_request, json.encode({
        "runtimeHost": {"directory": _runfile(ctx, host.directory), "entryPoint": host.entry_point, "launchMode": host.launch_mode, "runtimeIdentifier": host.runtime_identifier, "version": host.version, "environment": host.environment},
        "entry": _runfile(ctx, runtime),
        "assembly": name,
        "test": test,
        "testOptions": {
            "protocol": ctx.attr.test_protocol,
            "expectedExitCode": ctx.attr.expected_exit_code,
            "settings": _runfile(ctx, ctx.file.test_settings) if ctx.file.test_settings else None,
            "settingsOutput": ctx.attr.test_settings_output or None,
            "filterArgument": ctx.attr.test_filter_argument,
            "allowEmpty": ctx.attr.allow_empty_tests,
            "diagnostics": ctx.attr.test_diagnostics,
            "outputDirectories": ctx.attr.test_output_dirs,
            "workingDirectory": ctx.attr.test_working_directory or None,
            "runner": _runfile(ctx, def_tool.directory) + "/" + def_tool.path if def_tool else None,
            "adapters": [_runfile(ctx, tool[MSBuildTestToolInfo].directory) + "/" + tool[MSBuildTestToolInfo].path for tool in ctx.attr.test_adapters],
        } if test else None,
        "data": [{"source": _runfile(ctx, row.file), "path": row.destination} for row in runtime_data.to_list()],
    }))
    launcher = ctx.actions.declare_file(ctx.label.name)
    script = """#!/usr/bin/env bash
set -euo pipefail
runfiles="${RUNFILES_DIR:-${TEST_SRCDIR:-$0.runfiles}}"
export RULES_MSBUILD_RUNFILES="$runfiles"
exec "$runfiles/"%s "$runfiles/"%s run "$runfiles/"%s "$@"
""" % (_quote(_runfile(ctx, tc.dotnet)), _quote(_runfile(ctx, tc.runner)), _quote(_runfile(ctx, launch_request)))
    ctx.actions.write(launcher, script, is_executable = True)
    runfiles = ctx.runfiles(
        files = [tc.dotnet, tc.runner, runtime, launch_request] + [host.directory] + [row.file for row in runtime_data.to_list()] + ([ctx.file.test_settings] if test and ctx.file.test_settings else []),
        transitive_files = depset(transitive = [host.files] + [tc.runtime, tc.runner_support] + [tool[MSBuildTestToolInfo].files for tool in test_tools]),
    )
    return ([RunEnvironmentInfo(environment = ctx.attr.env)] if test else []) + [DefaultInfo(executable = launcher, files = depset([runtime]), runfiles = runfiles)]
