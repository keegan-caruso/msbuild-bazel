"""Logical names shared by local source and repository inputs."""

def input_path(file):
    """Returns the logical workspace path for a declared input.

    Args:
        file: A local source or external repository File.

    Returns:
        Its normalized workspace-relative destination.
    """
    path = file.short_path
    if path.startswith("../"):
        path = "/".join(path.split("/")[2:])
        if path.startswith("packages/"):
            return ".nuget/" + path
    return path.removeprefix("inputs/").removeprefix("controller/")
