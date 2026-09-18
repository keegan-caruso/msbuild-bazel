"""Declared, cacheable MSBuild discovery and preparation."""

load(":input_paths.bzl", "input_path")

DiscoveryPlanInfo = provider(doc = "Structural discovery tree shared by project bindings.", fields = ["directory", "validation"])

def _prepare(ctx):
    plan = ctx.actions.declare_directory(ctx.label.name + ".plan")
    discovery = ctx.actions.declare_directory(ctx.label.name + ".discovery")
    bodies = [f for f in ctx.files.srcs if input_path(f).endswith(".cs") and not input_path(f).startswith(".nuget/") and "/obj/" not in input_path(f)]
    structural = [f for f in ctx.files.srcs if f not in bodies]
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({
        "entry": ctx.attr.project,
        "output": discovery.path,
        "sourceNames": [input_path(f) for f in bodies],
        "diagnostics": diagnostics.path,
        "host": ctx.file.host.path,
        "runtimeRoots": ctx.attr.runtime_roots,
        "runtimeManifest": ctx.file.runtime_manifest.path if ctx.file.runtime_manifest else None,
        "sources": [{"source": f.path, "destination": input_path(f)} for f in structural],
        "controller": [{"source": f.path, "destination": input_path(f)} for f in ctx.files.controller],
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-prepare", "--request", request.path],
        inputs = depset(structural + ctx.files.runtime_manifest + ctx.files.controller + [ctx.file.host, ctx.file.runner, request], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [discovery, diagnostics],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildDiscover",
        # Discovery starts its own stricter native sandbox. macOS forbids nested
        # sandbox-exec; keep this trusted staging process local but cacheable.
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1"},
    )
    validation = []
    if ctx.file.layout:
        marker = ctx.actions.declare_file(ctx.label.name + ".layout-valid.json")
        check = ctx.actions.declare_file(ctx.label.name + ".validate-layout.json")
        ctx.actions.write(check, json.encode({"discovery": discovery.path, "layout": ctx.file.layout.path, "output": marker.path}))
        ctx.actions.run(
            executable = ctx.executable.dotnet,
            arguments = [ctx.file.runner.path, "owned-validate-layout", "--request", check.path],
            inputs = depset(ctx.files.controller + [ctx.file.runner, discovery, ctx.file.layout, check], transitive = [ctx.attr.sdk[DefaultInfo].files]),
            outputs = [marker],
            env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
            mnemonic = "MsbuildValidateLayout",
            execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
        )
        validation.append(marker)
    bind_request = ctx.actions.declare_file(ctx.label.name + ".bind.json")
    ctx.actions.write(bind_request, json.encode({
        "discovery": discovery.path,
        "output": plan.path,
        "sources": [{"source": f.path, "destination": input_path(f)} for f in bodies],
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "owned-bind-sources", "--request", bind_request.path],
        inputs = depset(validation + bodies + ctx.files.controller + [ctx.file.runner, discovery, bind_request], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [plan],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildBindSources",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset([plan])), DiscoveryPlanInfo(directory = discovery, validation = validation), OutputGroupInfo(discovery = depset([discovery]))]

msbuild_prepare = rule(implementation = _prepare, attrs = {
    "layout": attr.label(allow_single_file = True),
    "project": attr.string(mandatory = True),
    "srcs": attr.label_list(allow_files = True),
    "controller": attr.label_list(allow_files = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "host": attr.label(allow_single_file = True, mandatory = True),
    "runtime_roots": attr.string_list(),
    "runtime_manifest": attr.label(allow_single_file = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
