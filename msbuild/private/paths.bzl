"""Logical paths, runfiles and request serialization."""

TOOLCHAIN = Label("//msbuild:toolchain_type")
RUNTIME_TOOLCHAIN = Label("//msbuild:runtime_toolchain_type")
NATIVE_TOOLCHAIN = Label("//msbuild:native_toolchain_type")

def quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"

def runfile(ctx, file):
    if file.short_path.startswith("../"):
        return file.short_path[3:]
    return ctx.workspace_name + "/" + file.short_path
