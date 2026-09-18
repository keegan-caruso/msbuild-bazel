"""Logical names shared by local source and repository inputs."""

def input_path(file):
    path = file.short_path
    if path.startswith("../"):
        path = "/".join(path.split("/")[2:])
        if path.startswith("packages/"):
            return ".nuget/" + path
    return path.removeprefix("inputs/").removeprefix("controller/")
