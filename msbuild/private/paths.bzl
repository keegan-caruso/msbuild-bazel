"""Logical paths, runfiles and request serialization."""

TOOLCHAIN = Label("//msbuild:toolchain_type")
RUNTIME_TOOLCHAIN = Label("//msbuild:runtime_toolchain_type")

def runtime_package(row, ctx = None):
    return {"id": row.id, "version": row.version, "directory": runfile(ctx, row.directory) if ctx else row.directory.path}

def logical(file):
    path = file.short_path
    if path.startswith("../"):
        # Keep repository identities in the logical namespace.
        return "external/" + path[3:]
    return path

def input_file(file):
    return {"source": file.path, "path": logical(file)}

def mapped_imports(ctx, bindings = None):
    """Return import request rows using explicitly assigned logical paths.

    Args:
        ctx: Rule context with import_paths bindings.
        bindings: Optional explicit label/path map.

    Returns:
        Source and logical path dictionaries for the build request.
    """
    rows = []
    for target, path in (ctx.attr.import_paths if bindings == None else bindings).items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("import_paths requires one file per label")
        rows.append({"source": files[0].path, "path": path})
    return rows

def quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"

def runfile(ctx, file):
    if file.short_path.startswith("../"):
        return file.short_path[3:]
    return ctx.workspace_name + "/" + file.short_path
