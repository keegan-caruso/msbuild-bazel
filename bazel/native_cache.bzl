"""Opt-in native project cache with declared seeds and a sandboxed graph action."""

# buildifier: disable=name-conventions
NativeBundle = provider(doc = "Sealed native project bundles and entry runtime.", fields = ["bundle"])

def _native_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    plan = ctx.file.prepared_plan
    if not plan and (not ctx.file.manifest or not ctx.file.restore):
        fail("manifest and restore or prepared_plan required")
    ctx.actions.write(request, json.encode({
        "entry": ctx.attr.project,
        "executionNonce": ctx.attr.execution_nonce,
        "output": output.path,
        "diagnostics": diagnostics.path,
        "manifest": plan.path + "/manifest.json" if plan else ctx.file.manifest.path,
        "preparedPlan": plan.path if plan else None,
        "restore": plan.path + "/restore.json" if plan else ctx.file.restore.path,
        "sources": [{"source": f.path, "destination": f.short_path.removeprefix("src/")} for f in ctx.files.srcs],
        "seeds": [{"source": f.path, "destination": f.short_path.removeprefix("seeds/")} for f in ctx.files.seeds],
        "readProbe": ctx.attr.read_probe or None,
        "networkProbe": ctx.attr.network_probe or None,
        "writeProbe": ctx.attr.write_probe or None,
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--portable-request", request.path],
        inputs = depset(ctx.files.srcs + ctx.files.seeds + ctx.files.runner_support + [ctx.file.runner, request] + ([plan] if plan else [ctx.file.manifest, ctx.file.restore]), transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output, diagnostics],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildNativeCache",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset([output, diagnostics])), NativeBundle(bundle = output)]

msbuild_native_cache = rule(implementation = _native_impl, attrs = {
    "project": attr.string(mandatory = True),
    "srcs": attr.label_list(allow_files = True),
    "seeds": attr.label_list(allow_files = True),
    "prepared_plan": attr.label(allow_single_file = True),
    "manifest": attr.label(allow_single_file = True),
    "restore": attr.label(allow_single_file = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
    "read_probe": attr.string(),
    "network_probe": attr.string(),
    "write_probe": attr.string(),
    "execution_nonce": attr.string(doc = "Probe-only invalidation to test inner fallback despite an outer cache hit."),
})
