"""Acquire only the fixture's exact archive inventory."""

def _packages(ctx):
    declarations = ["load(%s, \"msbuild_nuget_package\", \"msbuild_package_lock\")" % repr(str(ctx.attr._defs)), 'package(default_visibility = ["//visibility:public"])']
    names = []
    archives = []
    for index, package in enumerate(json.decode(ctx.read(ctx.attr.inventory))):
        name = "package_%s" % index
        archive = package["id"].lower() + "." + package["version"] + ".nupkg"
        ctx.download(package["url"], output = archive, sha256 = package["sha256"])
        declarations.append("msbuild_nuget_package(name=%s, package_id=%s, version=%s, archive=%s, archive_sha256=%s, content_hash=%s)" % tuple([repr(v) for v in [name, package["id"], package["version"], archive, package["sha256"], package["content_hash"]]]))
        names.append(":" + name)
        archives.append(archive)
    declarations.append("msbuild_package_lock(name=\"lock\", packages=%s)" % repr(names))
    declarations.append("filegroup(name=\"archives\", srcs=%s)" % repr(archives))
    ctx.file("BUILD.bazel", "\n".join(declarations) + "\n")

package_repository = repository_rule(
    implementation = _packages,
    attrs = {
        "inventory": attr.label(mandatory = True, allow_single_file = True),
        "_defs": attr.label(default = Label("@rules_msbuild//msbuild:defs.bzl")),
    },
)
