"""Local SDK repository used by the explicit MSBuild toolchain."""

def _sdk_impl(ctx):
    ctx.symlink(ctx.attr.path, "sdk")
    ctx.file("runtime-roots.json", "[]")
    ctx.file("BUILD.bazel", 'filegroup(name="files", srcs=glob(["sdk/**"], exclude=["sdk/**/BUILD", "sdk/**/BUILD.bazel"], allow_empty=False), visibility=["//visibility:public"])\nexports_files(["sdk/dotnet", "runtime-roots.json"])\n')

local_dotnet_sdk = repository_rule(
    implementation = _sdk_impl,
    attrs = {"path": attr.string(mandatory = True)},
    local = True,
)
