"""Assemble and bind a declared native compiler tree for MSBuild actions."""

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

def _package_name(package):
    return package["name"]

def _native_toolchain_packages(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    root = ctx.actions.declare_directory(ctx.label.name + ".root")
    request = ctx.actions.declare_file(ctx.label.name + ".json")
    packages = []
    archives = []
    for target, digest in ctx.attr.packages.items():
        files = target.files.to_list()
        if len(files) != 1 or not files[0].basename.endswith(".deb"):
            fail("Each native toolchain package must provide one .deb file")
        archive = files[0]
        name = archive.basename[:-4]
        packages.append({
            "name": name,
            "archive": archive.path,
            "sha256": digest,
            "licensePath": "usr/share/doc/" + name + "/copyright",
        })
        archives.append(archive)
    packages = sorted(packages, key = _package_name)
    ctx.actions.write(request, json.encode({
        "packages": packages,
        "manifest": ctx.file.manifest.path,
        "output": root.path,
    }))
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "native-toolchain-packages", request.path],
        inputs = depset(archives + [ctx.file.manifest, request, tc.runner], transitive = [tc.runtime, tc.runner_support]),
        outputs = [root],
        mnemonic = "MSBuildNativeToolchainPackages",
        env = {"LANG": "en_US.UTF-8"},
        # dpkg-deb comes from the qualified Ubuntu build image, not a declared tool.
        execution_requirements = {"block-network": "1", "no-remote": "1"},
    )
    return [DefaultInfo(files = depset([root]))]

msbuild_native_toolchain_packages = rule(
    implementation = _native_toolchain_packages,
    attrs = {
        "packages": attr.label_keyed_string_dict(allow_files = [".deb"], mandatory = True),
        "manifest": attr.label(allow_single_file = True, mandatory = True),
    },
    toolchains = [_TOOLCHAIN],
)

def _native_toolchain(ctx):
    if not ctx.file.root.is_directory:
        fail("Native toolchain root must be a single tree artifact")
    return [platform_common.ToolchainInfo(root = ctx.file.root)]

msbuild_native_toolchain = rule(
    implementation = _native_toolchain,
    attrs = {"root": attr.label(allow_single_file = True, mandatory = True)},
)
