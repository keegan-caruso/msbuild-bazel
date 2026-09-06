"""Explicit two-project experiment; restore is prepared before these actions."""

MsbuildBundle = provider(fields = ["directory"])

def _msbuild_project_impl(ctx):
    for key in ctx.attr.build_environment:
        if not key.startswith("SPIKE_INPUT_"):
            fail("build_environment keys must start with SPIKE_INPUT_")
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    dependency = ctx.attr.dependency[MsbuildBundle].directory if ctx.attr.dependency else None
    ctx.actions.write(request, json.encode({
        "project": ctx.attr.project,
        "sources": [{"source": f.path, "destination": f.short_path.removeprefix("src/")} for f in ctx.files.srcs],
        "restore": [f.path for f in ctx.files.restore],
        "packages": [{"source": f.path, "destination": f.short_path.removeprefix("packages/")} for f in ctx.files.packages],
        "package_manifest": ctx.file.package_manifest.path if ctx.file.package_manifest else None,
        "plugin": ctx.file.plugin.path,
        "output": output.path,
        "diagnostics": diagnostics.path,
        "dependency": dependency.path if dependency else None,
        "undeclared_probe": ctx.attr.undeclared_probe,
        "native_manifest": ctx.file.native_manifest.path if ctx.file.native_manifest else None,
        "native_files": [{"source": f.path, "destination": "/".join(f.short_path.split("/")[2:])} for f in ctx.files.native_runtime],
    }))
    ctx.actions.run(
        inputs = depset(ctx.files.runner_support + ctx.files.native_runtime + ([ctx.file.native_manifest] if ctx.file.native_manifest else []) + ctx.files.srcs + ctx.files.restore + ctx.files.packages +
                        ([ctx.file.package_manifest] if ctx.file.package_manifest else []) + [request, ctx.file.plugin, ctx.file.runner, ctx.file.host_identity] +
                        ([dependency] if dependency else []), transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output, diagnostics],
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--request", request.path],
        env = dict({"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}, **ctx.attr.build_environment),
        mnemonic = "MsbuildProject",
        progress_message = "MSBuild %s with dependency replay" % ctx.attr.project,
        execution_requirements = {"block-network": "1", "no-remote": "1"},
    )
    return [DefaultInfo(files = depset([output, diagnostics])), MsbuildBundle(directory = output)]

msbuild_project = rule(
    implementation = _msbuild_project_impl,
    attrs = {
        "project": attr.string(mandatory = True, values = ["Shared", "App"]),
        "srcs": attr.label_list(allow_files = True),
        "restore": attr.label_list(allow_files = True),
        "packages": attr.label_list(allow_files = True),
        "package_manifest": attr.label(allow_single_file = True),
        "plugin": attr.label(allow_single_file = True, mandatory = True),
        "runner": attr.label(allow_single_file = True, mandatory = True),
        "runner_support": attr.label_list(allow_files = True),
        "sdk": attr.label(mandatory = True),
        "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
        "native_runtime": attr.label(allow_files = True),
        "native_manifest": attr.label(allow_single_file = True),
        "host_identity": attr.label(allow_single_file = True, mandatory = True),
        "build_environment": attr.string_dict(),
        "dependency": attr.label(providers = [MsbuildBundle]),
        "undeclared_probe": attr.string(),
    },
)

def _sdk_impl(ctx):
    ctx.symlink(ctx.attr.path, "sdk")
    ctx.file("BUILD.bazel", 'filegroup(name="files", srcs=glob(["sdk/**"], exclude=["sdk/**/BUILD", "sdk/**/BUILD.bazel"]), visibility=["//visibility:public"])\nexports_files(["sdk/dotnet"])\n')

local_dotnet_sdk = repository_rule(
    implementation = _sdk_impl,
    attrs = {"path": attr.string(mandatory = True)},
    local = True,
)


# Derive inputs from the manifest so Bazel hashes the same files the runner validates.
def _native_runtime_impl(ctx):
    manifest = json.decode(ctx.read(ctx.attr.manifest))
    for path in manifest["storePaths"]:
        ctx.symlink(path, path.split("/")[-1])
    ctx.file("BUILD.bazel", "filegroup(name=\"files\", srcs=" + json.encode(manifest["files"]) + ", visibility=[\"//visibility:public\"])\n")

local_native_runtime = repository_rule(
    implementation = _native_runtime_impl,
    attrs = {"manifest": attr.label(mandatory = True)},
    local = True,
)
