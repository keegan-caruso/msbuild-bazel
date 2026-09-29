"""Locked NuGet extraction and package closures."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")
load(":providers.bzl", "MSBuildPackageInfo", "MSBuildPackageLockInfo")

def _package(ctx, generated = False):
    tc = ctx.toolchains[_TOOLCHAIN]
    output = ctx.actions.declare_directory(ctx.label.name + ".package")
    request = ctx.actions.declare_file(ctx.label.name + ".package.json")
    ctx.actions.write(request, json.encode({"id": ctx.attr.package_id, "version": ctx.attr.version, "archive": ctx.file.archive.path, "contentHash": "" if generated else ctx.attr.content_hash, "archiveSha256": "" if generated else ctx.attr.archive_sha256, "generated": generated, "output": output.path}))
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "extract", request.path],
        inputs = depset([ctx.file.archive, request, tc.runner], transitive = [tc.runtime, tc.runner_support]),
        outputs = [output],
        mnemonic = "MSBuildNugetExtract",
        env = {"LANG": "en_US.UTF-8"},
        execution_requirements = {"block-network": "1"},
    )
    rows = {ctx.attr.package_id.lower(): {"id": ctx.attr.package_id, "version": ctx.attr.version, "directory": output.path}}
    for dep in ctx.attr.deps:
        for row in dep[MSBuildPackageInfo].rows:
            if row["id"].lower() in rows and rows[row["id"].lower()] != row:
                fail("Conflicting locked package: " + row["id"])
            rows[row["id"].lower()] = row
    files = depset([output], transitive = [dep[MSBuildPackageInfo].files for dep in ctx.attr.deps])
    return [DefaultInfo(files = files), MSBuildPackageInfo(id = ctx.attr.package_id, version = ctx.attr.version, directory = output, rows = rows.values(), files = files, archives = depset([ctx.file.archive], transitive = [dep[MSBuildPackageInfo].archives for dep in ctx.attr.deps]))]

msbuild_nuget_package = rule(implementation = _package, attrs = {
    "package_id": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "archive": attr.label(allow_single_file = [".nupkg"], mandatory = True),
    "content_hash": attr.string(mandatory = True),
    "archive_sha256": attr.string(mandatory = True),
    "deps": attr.label_list(providers = [MSBuildPackageInfo]),
}, toolchains = [_TOOLCHAIN])

def _generated_package(ctx):
    if ctx.file.archive.is_source:
        fail("Generated NuGet packages must be Bazel action outputs; use msbuild_nuget_package for acquired archives")
    return _package(ctx, generated = True)

msbuild_generated_nuget_package = rule(implementation = _generated_package, attrs = {
    "package_id": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "archive": attr.label(allow_single_file = [".nupkg"], mandatory = True),
    "deps": attr.label_list(providers = [MSBuildPackageInfo]),
}, toolchains = [_TOOLCHAIN])

def _package_union(infos):
    rows = {}
    for info in infos:
        for row in info.rows:
            key = row["id"].lower()
            if key in rows and rows[key] != row:
                fail("Conflicting package set: " + key)
            rows[key] = row
    return rows.values(), depset(transitive = [info.files for info in infos])

def _package_dependencies(ctx):
    package = ctx.attr.package[MSBuildPackageInfo]
    rows, files = _package_union([package] + [dep[MSBuildPackageInfo] for dep in ctx.attr.deps])
    return [DefaultInfo(files = files), MSBuildPackageInfo(id = package.id, version = package.version, directory = package.directory, rows = rows, files = files, archives = depset(transitive = [package.archives] + [dep[MSBuildPackageInfo].archives for dep in ctx.attr.deps]))]

msbuild_nuget_dependencies = rule(implementation = _package_dependencies, attrs = {
    "package": attr.label(providers = [MSBuildPackageInfo], mandatory = True),
    "deps": attr.label_list(providers = [MSBuildPackageInfo]),
})

def _package_lock(ctx):
    rows, files = _package_union([dep[MSBuildPackageInfo] for dep in ctx.attr.packages])
    return [DefaultInfo(files = files), MSBuildPackageLockInfo(rows = rows, files = files, archives = depset(transitive = [dep[MSBuildPackageInfo].archives for dep in ctx.attr.packages]))]

msbuild_package_lock = rule(implementation = _package_lock, attrs = {
    "packages": attr.label_list(providers = [MSBuildPackageInfo]),
})
