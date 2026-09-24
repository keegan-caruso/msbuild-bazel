"""Explicit MSBuild execution toolchain."""

def _toolchain(ctx):
    # Archive extraction runs a managed program, not MSBuild. Keep the host and
    # CoreCLR runtime, plus any separately declared platform runtime closure.
    # Compilation still receives the complete SDK below.
    sdk_root = ctx.executable.dotnet.dirname + "/"
    runtime = depset([file for file in ctx.attr.sdk[DefaultInfo].files.to_list() if not file.path.startswith(sdk_root) or file == ctx.executable.dotnet or file.path.startswith(sdk_root + "host/") or file.path.startswith(sdk_root + "shared/Microsoft.NETCore.App/")])
    worker_tools = ctx.actions.declare_file(ctx.label.name + ".worker-tools.json")
    ctx.actions.write(worker_tools, json.encode({
        "sdk": [file.path for file in ctx.attr.sdk[DefaultInfo].files.to_list()],
        "runner": [file.path for file in depset([ctx.file.runner] + ctx.files.runner_support).to_list()],
    }))
    return [platform_common.ToolchainInfo(
        worker_tools = worker_tools,
        dotnet = ctx.executable.dotnet,
        sdk = ctx.attr.sdk[DefaultInfo].files,
        runtime = runtime,
        runner = ctx.file.runner,
        runner_support = depset(ctx.files.runner_support),
        sdk_version = ctx.attr.sdk_version,
        runtime_manifest = ctx.file.runtime_manifest,
    )]

msbuild_toolchain = rule(
    implementation = _toolchain,
    attrs = {
        "dotnet": attr.label(executable = True, allow_single_file = True, cfg = "exec", mandatory = True),
        "sdk": attr.label(mandatory = True, cfg = "exec"),
        "runner": attr.label(allow_single_file = True, mandatory = True, cfg = "exec"),
        "runner_support": attr.label_list(allow_files = True, cfg = "exec"),
        "runtime_manifest": attr.label(allow_single_file = True, mandatory = True, cfg = "exec"),
        "sdk_version": attr.string(default = "10.0.400"),
    },
)
