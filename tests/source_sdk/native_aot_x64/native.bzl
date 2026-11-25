"""Extract a declared compiler/sysroot closure from verified native packages."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildLayoutInfo")

def _native(ctx):
    root = ctx.actions.declare_directory(ctx.label.name + ".layout")
    ctx.actions.run_shell(
        inputs = [ctx.file.archive, ctx.file.clang, ctx.file.objcopy],
        outputs = [root],
        arguments = [ctx.file.archive.path, root.path, ctx.file.clang.path, ctx.file.objcopy.path],
        command = """set -eu
mkdir -p "$2"
# Omit merged-root aliases: graph staging dereferences them and duplicates /usr.
tar -xf "$1" -C "$2"
rm -f "$2/bin" "$2/lib" "$2/sbin"
cp "$3" "$2/clang"
cp "$4" "$2/objcopy"
chmod +x "$2/clang" "$2/objcopy"
""",
        mnemonic = "PinnedNativeTools",
    )
    return [DefaultInfo(files = depset([root])), MSBuildLayoutInfo(directory = root)]

native = rule(
    implementation = _native,
    attrs = {
        "archive": attr.label(allow_single_file = True),
        "clang": attr.label(allow_single_file = True),
        "objcopy": attr.label(allow_single_file = True),
    },
)
