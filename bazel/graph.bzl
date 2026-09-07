"""Generated configured-project actions; restore occurs during preparation."""
GraphBundle = provider(fields = ["bundles"])

def _graph_project_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    dependencies = depset(transitive = [dep[GraphBundle].bundles for dep in ctx.attr.dependencies])
    ctx.actions.write(request, json.encode({
        "project": "Shared",
        "graph_project": ctx.attr.project,
        "graph_dependencies": [f.path for f in dependencies.to_list()],
        "sources": [{"source": f.path, "destination": f.short_path.removeprefix("src/")} for f in ctx.files.srcs],
        "restore": [f.path for f in ctx.files.restore],
        "packages": [{"source": f.path, "destination": f.short_path.removeprefix("packages/")} for f in ctx.files.packages],
        "package_manifest": ctx.file.package_manifest.path if ctx.file.package_manifest else None,
        "plugin": ctx.file.plugin.path, "build_props": ctx.file.build_props.path,
        "build_targets": ctx.file.build_targets.path,
        "output": output.path, "diagnostics": diagnostics.path,
        "dependency": None, "undeclared_probe": "", "native_manifest": None, "native_files": [],
    }))
    ctx.actions.run(
        inputs = depset(ctx.files.srcs + ctx.files.restore + ctx.files.packages +
            ([ctx.file.package_manifest] if ctx.file.package_manifest else []) + ctx.files.runner_support +
            [request, ctx.file.plugin, ctx.file.runner, ctx.file.build_props, ctx.file.build_targets, ctx.file.host_identity],
            transitive = [dependencies, ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output, diagnostics], executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--request", request.path],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildProject", progress_message = "MSBuild " + ctx.attr.project,
        execution_requirements = {"block-network": "1", "no-remote": "1"},
    )
    return [DefaultInfo(files = depset([output, diagnostics])),
            GraphBundle(bundles = depset([output], transitive = [dependencies]))]

graph_project = rule(implementation = _graph_project_impl, attrs = {
    "project": attr.string(mandatory = True),
    "srcs": attr.label_list(allow_files = True), "restore": attr.label_list(allow_files = True),
    "packages": attr.label_list(allow_files = True),
    "package_manifest": attr.label(allow_single_file = True),
    "dependencies": attr.label_list(providers = [GraphBundle]),
    "plugin": attr.label(allow_single_file = True, mandatory = True),
    "build_props": attr.label(allow_single_file = True, mandatory = True),
    "build_targets": attr.label(allow_single_file = True, mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "host_identity": attr.label(allow_single_file = True, mandatory = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
