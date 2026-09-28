"""Extract a locked native toolchain archive as a Bazel tree input."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")

def _native_toolchain_archive(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    root = ctx.actions.declare_directory(ctx.label.name + ".root")
    request = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(request, json.encode({
        "archive": ctx.file.archive.path,
        "archiveSha256": ctx.attr.archive_sha256,
        "output": root.path,
    }))
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "native-toolchain", request.path],
        inputs = depset([ctx.file.archive, request, tc.runner], transitive = [tc.runtime, tc.runner_support]),
        outputs = [root],
        mnemonic = "MSBuildNativeToolchainExtract",
        env = {"LANG": "en_US.UTF-8"},
        execution_requirements = {"block-network": "1"},
    )
    return [DefaultInfo(files = depset([root]))]

msbuild_native_toolchain_archive = rule(
    implementation = _native_toolchain_archive,
    attrs = {
        "archive": attr.label(allow_single_file = [".tar.gz"], mandatory = True),
        "archive_sha256": attr.string(mandatory = True),
    },
    toolchains = [_TOOLCHAIN],
)
