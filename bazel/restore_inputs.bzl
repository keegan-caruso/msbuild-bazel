"""Normalize host-specific restore metadata as declared action outputs."""

load(":input_paths.bzl", "input_path")
load(":nuget_package.bzl", "NugetPackageSetInfo", "package_files", "package_rows")

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

def _locked_restore(ctx):
    bodies = [f for f in ctx.files.srcs if input_path(f).endswith(".cs") and not input_path(f).startswith(".nuget/") and "/obj/" not in input_path(f)]
    structural = [f for f in ctx.files.srcs if f not in bodies]
    outputs = []
    declared = []
    for project in ctx.attr.projects:
        parts = project.split("/")
        folder = "/".join(parts[:-1] + ["obj"])
        for leaf in ["project.assets.json", "project.nuget.cache", parts[-1] + ".nuget.g.props", parts[-1] + ".nuget.g.targets", parts[-1] + ".nuget.dgspec.json"]:
            name = folder + "/" + leaf
            output = ctx.actions.declare_file("restore_inputs.files/" + name)
            outputs.append(output)
            declared.append({"name": name, "output": output.path})
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({
        "entry": ctx.attr.project,
        "projects": ctx.attr.projects,
        "config": ctx.attr.config,
        "sources": [{"source": f.path, "destination": input_path(f)} for f in structural],
        "packageDirectories": package_rows(ctx.attr.package_set),
        "sourceNames": [input_path(f) for f in bodies],
        "outputs": declared,
        "diagnostics": diagnostics.path,
        "runtimeManifest": ctx.file.runtime_manifest.path,
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-locked-restore", "--request", request.path],
        inputs = depset(structural + package_files(ctx.attr.package_set) + ctx.files.controller + [ctx.file.runner, ctx.file.runtime_manifest, request], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = outputs + [diagnostics],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildLockedRestore",
        # Own deny-by-default sandbox, as for discovery; no nested macOS sandbox.
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset(outputs))]

msbuild_locked_restore = rule(implementation = _locked_restore, attrs = {
    "package_set": attr.label(providers = [NugetPackageSetInfo]),
    "srcs": attr.label_list(allow_files = True),
    "project": attr.string(mandatory = True),
    "projects": attr.string_list(mandatory = True),
    "config": attr.string(mandatory = True),
    "runtime_manifest": attr.label(allow_single_file = True, mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "controller": attr.label_list(allow_files = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
