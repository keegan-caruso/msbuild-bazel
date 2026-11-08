"""Declared preparation for the pinned Linux ARM64 native runtime producers."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildLayoutInfo", "msbuild_native_toolchain_packages")
load("@rules_pkg//pkg:tar.bzl", "pkg_tar")

_TOOLCHAIN = "@rules_msbuild//msbuild:toolchain_type"

def _versions(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    driver = ctx.attr.driver[MSBuildLayoutInfo].directory
    outputs = [ctx.actions.declare_file(ctx.label.name + "/" + name) for name in ["_version.h", "runtime_version.h", "_version.c"]]
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [driver.path + "/Task.dll", "versions", ctx.file.properties.path, ctx.file.header.path, ctx.file.runtime_header.path, ctx.file.implementation.path, ctx.attr.commit] + [file.path for file in outputs],
        inputs = depset([driver] + ctx.files.properties + ctx.files.header + ctx.files.runtime_header + ctx.files.implementation, transitive = [tc.runtime]),
        outputs = outputs,
        mnemonic = "RuntimeNativeVersions",
    )
    return [DefaultInfo(files = depset(outputs)), OutputGroupInfo(header = depset([outputs[0]]), runtime_header = depset([outputs[1]]), implementation = depset([outputs[2]]))]

native_versions = rule(
    implementation = _versions,
    attrs = {
        "driver": attr.label(providers = [MSBuildLayoutInfo], cfg = "exec", mandatory = True),
        "properties": attr.label(allow_single_file = True, mandatory = True),
        "header": attr.label(allow_single_file = True, mandatory = True),
        "runtime_header": attr.label(allow_single_file = True, mandatory = True),
        "implementation": attr.label(allow_single_file = True, mandatory = True),
        "commit": attr.string(mandatory = True),
    },
    toolchains = [_TOOLCHAIN],
)

def _export(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    driver = ctx.attr.driver[MSBuildLayoutInfo].directory
    root = ctx.file.root
    output = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [driver.path + "/Task.dll", "export", root.path + "/usr/bin/bwrap", output.path],
        inputs = depset([driver, root], transitive = [tc.runtime]),
        outputs = [output],
        mnemonic = "RuntimeNativeSandbox",
    )
    return [DefaultInfo(files = depset([output]))]

native_sandbox = rule(
    implementation = _export,
    attrs = {"driver": attr.label(providers = [MSBuildLayoutInfo], cfg = "exec", mandatory = True), "root": attr.label(allow_single_file = True, mandatory = True)},
    toolchains = [_TOOLCHAIN],
)

def native_inputs(name, commit, packages):
    """Prepare versioned sources and native tools as cacheable build outputs.

    Args:
        name: Source archive target name.
        commit: Pinned upstream source commit.
        packages: Verified native package labels mapped to their SHA-256 hashes.
    """
    native_versions(
        name = "versions",
        driver = ":driver",
        properties = "@runtime_source//:eng/Versions.props",
        header = "@runtime_source//:eng/native/version/_version.h",
        runtime_header = "@runtime_source//:eng/native/version/runtime_version.h",
        implementation = "@runtime_source//:eng/native/version/_version.c",
        commit = commit,
    )
    for group in ["header", "runtime_header", "implementation"]:
        native.filegroup(name = group, srcs = [":versions"], output_group = group)
    pkg_tar(
        name = name,
        deps = ["@runtime_source//:native_sources"],
        mode = "0644",
        files = {":header": "artifacts/obj/_version.h", ":runtime_header": "artifacts/obj/runtime_version.h", ":implementation": "artifacts/obj/_version.c"},
        preserve_mode = False,
        mtime = 0,
        portable_mtime = False,
        stamp = 0,
    )
    if packages:
        msbuild_native_toolchain_packages(name = "tools", packages = packages, archive = True, exclude_prefixes = ["usr/share/locale", "usr/share/man", "usr/share/info", "usr/share/doc"], symlinks = {"usr/bin/sh": "usr/bin/bash", "usr/bin/cc": "usr/bin/gcc", "usr/bin/c++": "usr/bin/g++", "usr/bin/awk": "usr/bin/mawk", "usr/sbin/rmt": "usr/sbin/rmt-tar"})
        native.filegroup(name = "toolchain_files", srcs = [":tools"], output_group = "archive")
        pkg_tar(
            name = "toolchain",
            deps = [":toolchain_files"],
            symlinks = {"bin": "usr/bin", "lib": "usr/lib", "sbin": "usr/sbin"},
            empty_dirs = ["source", "proc", "dev", "tmp"],
            preserve_mode = True,
            mtime = 0,
            portable_mtime = False,
            stamp = 0,
        )
        native_sandbox(name = "bwrap", driver = ":driver", root = ":tools")
