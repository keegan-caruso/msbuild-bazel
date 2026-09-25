"""Pinned native test inputs using only Bazel's repository download/extract APIs."""

def _native_runtime_impl(ctx):
    lock = json.decode(ctx.read(ctx.attr.lock))
    for package in lock["packages"]:
        if package.get("vnc_only", False) and not ctx.attr.include_vnc:
            continue
        archive = "archives/" + package["name"]
        ctx.download_and_extract(
            url = package["url"],
            sha256 = package["sha256"],
            output = archive,
            type = "deb",
        )
        payloads = [path for path in ctx.path(archive).readdir() if path.basename.startswith("data.tar.")]
        if len(payloads) != 1:
            fail("Expected exactly one Debian data archive: " + package["name"])
        ctx.extract(payloads[0], output = "packages/" + package["name"])
        ctx.delete(archive)
    exports = []
    for entry in lock["files"]:
        if entry.get("vnc_only", False) and not ctx.attr.include_vnc:
            continue
        source = ctx.path("packages/" + entry["package"] + "/" + entry["path"])
        if not source.exists:
            fail("Missing locked native file: " + str(source))
        ctx.symlink(source, entry["destination"])
        exports.append(entry["destination"])
    ctx.file("BUILD.bazel", "exports_files(%s, visibility = [\"//visibility:public\"])\nfilegroup(name = \"runtime_files\", srcs = %s, visibility = [\"//visibility:public\"])\n" % (repr(exports), repr(exports)))

native_runtime = repository_rule(
    implementation = _native_runtime_impl,
    attrs = {
        "lock": attr.label(mandatory = True, allow_single_file = True),
        "include_vnc": attr.bool(),
    },
)
