"""Explicit two-project experiment; restore is prepared before these actions."""

MsbuildBundle = provider(fields = ["directory"])

def _msbuild_project_impl(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    dependency = ctx.attr.dependency[MsbuildBundle].directory if ctx.attr.dependency else None
    ctx.actions.write(request, json.encode({
        "project": ctx.attr.project,
        "sources": [{"source": f.path, "destination": f.short_path.removeprefix("src/")} for f in ctx.files.srcs],
        "restore": [f.path for f in ctx.files.restore],
        "plugin": ctx.file.plugin.path,
        "dotnet": ctx.file.dotnet.path,
        "output": output.path,
        "dependency": dependency.path if dependency else None,
        "undeclared_probe": ctx.attr.undeclared_probe,
    }))
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + ctx.files.restore + [request, ctx.file.plugin, ctx.file.runner] +
                        ([dependency] if dependency else []), transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output],
        command = 'exec "$1" "$2" --request "$3"',
        arguments = [ctx.attr.python, ctx.file.runner.path, request.path],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildProject",
        progress_message = "MSBuild %s with dependency replay" % ctx.attr.project,
        execution_requirements = {"block-network": "1"},
    )
    return [DefaultInfo(files = depset([output])), MsbuildBundle(directory = output)]

msbuild_project = rule(
    implementation = _msbuild_project_impl,
    attrs = {
        "project": attr.string(mandatory = True, values = ["Shared", "App"]),
        "srcs": attr.label_list(allow_files = True),
        "restore": attr.label_list(allow_files = True),
        "plugin": attr.label(allow_single_file = True, mandatory = True),
        "runner": attr.label(allow_single_file = True, mandatory = True),
        "sdk": attr.label(mandatory = True),
        "dotnet": attr.label(allow_single_file = True, mandatory = True),
        "python": attr.string(mandatory = True),
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
