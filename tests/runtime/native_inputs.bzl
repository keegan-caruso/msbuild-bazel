"""Declared preparation for the pinned Linux ARM64/x64 native runtime producers."""

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

def native_inputs(name, commit, packages, architecture = "arm64"):
    """Prepare versioned sources and native tools as cacheable build outputs.

    Args:
        name: Source archive target name.
        commit: Pinned upstream source commit.
        packages: Verified native package labels mapped to their SHA-256 hashes.
        architecture: Native producer architecture, arm64 or x64.
    """
    if architecture not in ["arm64", "x64"]:
        fail("Unsupported native runtime architecture: " + architecture)
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
        native_toolchain_inputs(name = "toolchain", packages = packages, architecture = architecture)
        native_sandbox(name = "bwrap", driver = ":driver", root = ":tools")

def native_toolchain_inputs(name, packages, architecture = "arm64", sdk = False):
    """Assemble a pinned compiler root without source/version generation.

    Args:
        name: Final toolchain archive target; companion targets use fixed names.
        packages: Verified package labels mapped to SHA-256 hashes.
        architecture: Native producer architecture, arm64 or x64.
        sdk: Include deterministic SDK prerequisite setup.
    """
    if architecture not in ["arm64", "x64"]:
        fail("Unsupported native runtime architecture: " + architecture)

    # Package maintainer scripts are not run; declare tzdata localtime as UTC.
    msbuild_native_toolchain_packages(name = "tools", packages = packages, archive = True, exclude_prefixes = ["usr/share/locale", "usr/share/man", "usr/share/info", "usr/share/doc"] + (["usr/lib/ssl/cert.pem"] if sdk else []), symlinks = {"etc/localtime": "usr/share/zoneinfo/Etc/UTC", "usr/bin/sh": "usr/bin/bash", "usr/bin/cc": "usr/bin/gcc", "usr/bin/c++": "usr/bin/g++", "usr/bin/awk": "usr/bin/mawk", "usr/bin/clang": "usr/bin/clang-18", "usr/bin/clang++": "usr/bin/clang++-18", "usr/bin/clang-cpp": "usr/bin/clang-cpp-18", "usr/bin/lld": "usr/bin/lld-18", "usr/bin/ld.lld": "usr/bin/ld.lld-18", "usr/bin/llvm-ar": "usr/bin/llvm-ar-18", "usr/bin/llvm-nm": "usr/bin/llvm-nm-18", "usr/bin/llvm-objcopy": "usr/bin/llvm-objcopy-18", "usr/bin/llvm-objdump": "usr/bin/llvm-objdump-18", "usr/bin/llvm-ranlib": "usr/bin/llvm-ranlib-18", "usr/bin/llvm-readelf": "usr/bin/llvm-readelf-18", "usr/bin/llvm-strip": "usr/bin/llvm-strip-18", "usr/bin/llvm-config": "usr/bin/llvm-config-18", "usr/bin/llvm-profdata": "usr/bin/llvm-profdata-18", "usr/sbin/rmt": "usr/sbin/rmt-tar"})
    native.filegroup(name = "toolchain_files", srcs = [":tools"], output_group = "archive")
    files = {}
    if sdk:
        # ca-certificates' postinst normally creates this concatenation. Inputs
        # come only from the declared package root, sorted by certificate path.
        native.genrule(
            name = "certificate_bundle",
            srcs = [":tools"],
            outs = ["ca-certificates.crt"],
            cmd = "find -L $(location :tools)/usr/share/ca-certificates -type f -name '*.crt' | LC_ALL=C sort | xargs cat > $@; test -s $@",
        )
        files[":certificate_bundle"] = "etc/ssl/certs/ca-certificates.crt"

        # Package maintainer scripts normally create account defaults. NuGet
        # retries user-profile discovery indefinitely if passwd is absent.
        for account_file, entries in {
            "passwd": ["root:x:0:0:root:/tmp:/bin/bash", "builder:x:1000:1000:Build user:/tmp:/bin/bash"],
            "group": ["root:x:0:", "builder:x:1000:"],
            "nsswitch.conf": ["passwd: files", "group: files", "hosts: files dns"],
        }.items():
            target = "sdk_" + account_file.replace(".", "_")
            native.genrule(
                name = target,
                outs = ["sdk-" + account_file],
                cmd = "printf '%s\\n' " + " ".join(["'" + entry + "'" for entry in entries]) + " > $@",
            )
            files[":" + target] = "etc/" + account_file
    aliases = {"bin": "usr/bin", "lib": "usr/lib", "sbin": "usr/sbin"}
    if architecture == "x64":
        aliases["lib64"] = "usr/lib64"
    if sdk:
        # OpenSSL's certificate alias is valid only after the bundle is added.
        aliases["usr/lib/ssl/cert.pem"] = "../../../etc/ssl/certs/ca-certificates.crt"
    pkg_tar(
        name = name,
        files = files,
        deps = [":toolchain_files"],
        symlinks = aliases,
        empty_dirs = ["source", "proc", "dev", "tmp"],
        preserve_mode = True,
        mtime = 0,
        portable_mtime = False,
        stamp = 0,
    )
