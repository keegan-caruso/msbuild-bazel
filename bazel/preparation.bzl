"""Declared, cacheable MSBuild discovery and preparation."""

def _prepare(ctx):
    plan = ctx.actions.declare_directory(ctx.label.name + ".plan")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({
        "entry": ctx.attr.project,
        "output": plan.path,
        "diagnostics": diagnostics.path,
        "host": ctx.file.host.path,
        "runtimeRoots": ctx.attr.runtime_roots,
        "sources": [{"source": f.path, "destination": f.short_path.removeprefix("inputs/")} for f in ctx.files.srcs],
        "controller": [{"source": f.path, "destination": f.short_path.removeprefix("controller/")} for f in ctx.files.controller],
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-prepare", "--request", request.path],
        inputs = depset(ctx.files.srcs + ctx.files.controller + [ctx.file.host, ctx.file.runner, request], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [plan, diagnostics],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildPrepare",
        # Discovery starts its own stricter native sandbox. macOS forbids nested
        # sandbox-exec; keep this trusted staging process local but cacheable.
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset([plan]))]

msbuild_prepare = rule(implementation = _prepare, attrs = {
    "project": attr.string(mandatory = True),
    "srcs": attr.label_list(allow_files = True),
    "controller": attr.label_list(allow_files = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "host": attr.label(allow_single_file = True, mandatory = True),
    "runtime_roots": attr.string_list(mandatory = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
