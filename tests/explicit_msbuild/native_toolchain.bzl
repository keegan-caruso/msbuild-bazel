"""Capture the Linux native toolchain for the AOT qualification fixture.

This test-only producer reads the local machine and therefore never enters an
action cache. The AOT consumer receives its output tree as a declared input.
"""

def _snapshot(ctx):
    root = ctx.actions.declare_directory(ctx.label.name + ".root")
    ctx.actions.run_shell(
        outputs = [root],
        command = """
set -eu
mkdir -p "$1/usr/share" "$1/etc"
cp -a /usr/bin /usr/include /usr/lib "$1/usr/"
rm -rf "$1/usr/lib/llvm-14/build"
if test -d /usr/share/icu; then cp -a /usr/share/icu "$1/usr/share/"; fi
cp -a /etc/os-release /etc/ld.so.cache /etc/passwd /etc/group "$1/etc/"
find "$1" -type l -xtype l -delete
if [ "$2" = "true" ]; then rm -f "$1/usr/bin/clang" "$1/usr/bin/gcc"; fi
""",
        arguments = [root.path, "true" if ctx.attr.omit_compiler else "false"],
        execution_requirements = {
            "no-cache": "1",
            "no-remote": "1",
            "no-sandbox": "1",
        },
    )
    return [DefaultInfo(files = depset([root]))]

native_toolchain_snapshot = rule(
    implementation = _snapshot,
    attrs = {"omit_compiler": attr.bool()},
)
