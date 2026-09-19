"""Cacheable package extraction; version resolution stays with locked NuGet restore."""

def _extract(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".package")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({
        "archive": ctx.file.archive.path,
        "package": ctx.attr.package,
        "contentHash": ctx.attr.content_hash,
        "pin": json.decode(ctx.attr.pin) if ctx.attr.pin else None,
        "output": output.path,
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-extract-package", "--request", request.path],
        inputs = depset([request, ctx.file.archive, ctx.file.runner] + ctx.files.runner_support, transitive = [ctx.attr.runtime[DefaultInfo].files]),
        outputs = [output],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "NugetExtractPackage",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset([output]))]

nuget_extract_package = rule(implementation = _extract, attrs = {
    "archive": attr.label(allow_single_file = True, mandatory = True),
    "package": attr.string(mandatory = True),
    "content_hash": attr.string(mandatory = True),
    "pin": attr.string(),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "runtime": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
