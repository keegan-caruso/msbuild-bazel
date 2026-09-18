"""Normalize host-specific restore metadata as declared action outputs."""

load(":input_paths.bzl", "input_path")

def _normalize(ctx):
    files = []
    outputs = []
    for source in ctx.files.srcs:
        name = input_path(source)
        output = ctx.actions.declare_file("restore_inputs.files/" + name)
        files.append({"source": source.path, "output": output.path, "name": name})
        outputs.append(output)
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({"files": files, "workspace": ctx.attr.workspace, "cache": ctx.attr.cache}))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-normalize-restore", "--request", request.path],
        inputs = depset(ctx.files.srcs + ctx.files.controller + [ctx.file.runner, request], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = outputs,
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildNormalizeRestore",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset(outputs))]

msbuild_normalize_restore = rule(implementation = _normalize, attrs = {
    "srcs": attr.label_list(allow_files = True),
    "workspace": attr.string(mandatory = True),
    "cache": attr.string(mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "controller": attr.label_list(allow_files = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
