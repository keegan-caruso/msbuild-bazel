"""Locked source-runtime products for the bounded independent JIT consumer."""

def _extract(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    ctx.actions.run_shell(
        inputs = [ctx.file.archive],
        outputs = [output],
        arguments = [ctx.file.archive.path, ctx.attr.sha256, ctx.attr.prefix, output.path],
        command = '''set -eu
printf '%s  %s\\n' "$2" "$1" | sha256sum -c -
mkdir -p "$4"
tar -xzf "$1" --strip-components=1 -C "$4" "$3"
''',
        mnemonic = "RuntimeJitProducts",
    )
    return [DefaultInfo(files = depset([output]))]

runtime_jit_products = rule(
    implementation = _extract,
    attrs = {
        "archive": attr.label(allow_single_file = True, mandatory = True),
        "sha256": attr.string(mandatory = True),
        "prefix": attr.string(mandatory = True, values = ["references", "core-root"]),
    },
)
