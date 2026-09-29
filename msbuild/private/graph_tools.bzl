"""Materialize the existing tool provider's full runtime closure once."""

load(":paths.bzl", "runtime_package")

def graph_tool_closure(ctx, tc, binding, index):
    """Compose the declared managed tool, packages and data for graph actions.

    Args:
        ctx: Owning rule context.
        tc: Execution SDK toolchain.
        binding: Managed tool binding provider.
        index: Stable position in the rule's bindings list.

    Returns:
        The composed tool directory artifact.
    """
    tool = binding.tool
    if tool.native:
        fail("Graph sync bindings require a managed task tool")
    output = ctx.actions.declare_directory(ctx.label.name + ".graph-tool-" + str(index))
    request = ctx.actions.declare_file(ctx.label.name + ".graph-tool-" + str(index) + ".json")
    ctx.actions.write(request, json.encode({
        "output": output.path,
        "tool": {
            "project": tool.project,
            "entryPoint": tool.entry_point,
            "layoutPrefix": tool.layout_prefix,
            "directories": [file.path for file in tool.directories.to_list()],
            "packages": [runtime_package(row) for row in tool.packages.to_list()],
            "data": [{"source": row.file.path, "path": row.destination} for row in tool.data],
        },
    }))
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "tool-layout", request.path],
        inputs = depset([request, tc.runner], transitive = [tc.runtime, tc.runner_support, tool.files]),
        outputs = [output],
        mnemonic = "MSBuildGraphTool",
    )
    return output
