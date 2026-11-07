"""Verified runtime sources with upstream BUILD files retained as source data."""

def _source(ctx):
    ctx.download_and_extract(
        url = ctx.attr.urls,
        sha256 = ctx.attr.sha256,
        type = "tar.gz",
        stripPrefix = "runtime-" + ctx.attr.commit,
    )

    # Brotli ships a Bazel package. Keep its authored BUILD bytes, while letting
    # this repository's single native-source glob own that directory as data.
    path = "src/native/external/brotli/BUILD.bazel"
    ctx.file(path + ".upstream", ctx.read(path), executable = False)
    ctx.delete(path)
    ctx.file("BUILD.bazel", """load("@rules_pkg//pkg:tar.bzl", "pkg_tar")
package(default_visibility = ["//visibility:public"])
exports_files(["eng/Versions.props", "eng/native/version/_version.h", "eng/native/version/runtime_version.h", "eng/native/version/_version.c"])
pkg_tar(
    name = "native_sources",
    srcs = glob(["src/coreclr/**", "src/native/**", "eng/native/**", "eng/common/native/**"], exclude = ["**/BUILD.bazel.upstream", "src/native/external/libunwind/README.md"]),
    files = {"src/native/external/brotli/BUILD.bazel.upstream": "src/native/external/brotli/BUILD.bazel"},
    symlinks = {"src/native/external/libunwind/README.md": "README"},
    strip_prefix = __SOURCE_PREFIX__,
    preserve_mode = True,
    mtime = 0,
    portable_mtime = False,
    stamp = 0,
)
""".replace("__SOURCE_PREFIX__", json.encode("/external/" + ctx.name)), executable = False)

runtime_source = repository_rule(
    implementation = _source,
    attrs = {"urls": attr.string_list(mandatory = True), "sha256": attr.string(mandatory = True), "commit": attr.string(mandatory = True)},
)
