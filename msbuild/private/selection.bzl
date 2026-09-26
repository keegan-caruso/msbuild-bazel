"""Explicit assembly selection where configured dependency branches converge."""

load(":providers.bzl", "MSBuildAssemblyInfo")

def assembly_node(info):
    """Return hashable identity and artifact metadata for a configured assembly.

    Args:
        info: Assembly provider.

    Returns:
        A compact dependency node.
    """
    return struct(project = info.project, reference_only = info.output_mode == "reference", assembly = info.assembly, reference = info.reference, runtime = info.runtime, identity = info.identity, restore_project = info.restore_project)

def select_closure(ctx, nodes, references, runtime_references, runtimes, direct):
    """Apply declared choices without changing the compilation of dependencies.

    Args:
        ctx: Consumer rule context.
        nodes: Configured dependency nodes.
        references: Transitive compiler references.
        runtime_references: Runtime-only compiler metadata closure.
        runtimes: Runtime artifact closure.
        direct: Declared direct compiler dependencies.

    Returns:
        Filtered artifact sets and identity checks for the build action.
    """
    explicit = {target[MSBuildAssemblyInfo].assembly: assembly_node(target[MSBuildAssemblyInfo]) for target in ctx.attr.assembly_selections}
    if len(explicit) != len(ctx.attr.assembly_selections):
        fail("Select one implementation per assembly")
    chosen = {}
    for node in depset(transitive = [dep.selections for dep in direct]).to_list():
        if node.assembly in chosen and chosen[node.assembly] != node and node.assembly not in explicit:
            fail("Conflicting inherited assembly selections: " + node.assembly)
        chosen[node.assembly] = node
    chosen.update(explicit)
    selection_nodes = depset(chosen.values())
    if not chosen:
        return struct(references = references, runtime_references = runtime_references, runtimes = runtimes, checks = [], files = [], selections = selection_nodes, reference_choices = {})
    choices = {}
    checks = []
    files = []
    dropped = {}
    candidates = nodes.to_list()
    active_runtimes = runtimes.to_list()
    for selected in chosen.values():
        if any([dep.project == selected.project and (dep.reference != selected.reference or dep.runtime != selected.runtime) for dep in direct]):
            fail("Assembly selection disagrees with a direct dependency; change deps explicitly: " + selected.project)
        if selected.assembly + ".dll" in choices:
            fail("Select one implementation per assembly: " + selected.assembly)
        matches = [n for n in candidates if n.assembly == selected.assembly]
        if selected.runtime not in active_runtimes:
            fail("Selected implementation is not in the active runtime closure: " + selected.project)
        if not any([n.reference == selected.reference and n.runtime == selected.runtime for n in matches]):
            fail("Assembly selection must name an existing configured dependency: " + selected.project)

        # Paired contracts carry reference-only dependency projects which do not
        # contribute runtime artifacts. Keep their identity checks, but do not
        # mistake them for competing implementations from unrelated projects.
        if any([n.project != selected.project and not (n.reference_only and n.runtime not in active_runtimes) for n in matches]):
            fail("Assembly selection cannot replace a different project: " + selected.assembly)
        choices[selected.assembly + ".dll"] = selected.reference
        for node in matches:
            if node.runtime != selected.runtime:
                dropped[node.runtime] = True
            checks.append({"selected": selected.identity.path, "candidate": node.identity.path, "restoreProject": selected.restore_project.path})
            files.extend([selected.identity, node.identity])

    def selected_references(values):
        return depset([choices.get(file.basename, file) for file in values.to_list()])

    return struct(references = selected_references(references), runtime_references = selected_references(runtime_references), runtimes = depset([file for file in runtimes.to_list() if file not in dropped]), checks = checks, files = files, selections = selection_nodes, reference_choices = choices)

def restore_key(framework, reference_framework, configuration, properties):
    """Identify restore metadata by the explicit producer configuration.

    Args:
        framework: Implementation target framework.
        reference_framework: Public compatibility framework.
        configuration: Effective MSBuild configuration.
        properties: Explicit global property dictionary.

    Returns:
        A stable serialized key, hashed only when used as a filesystem path.
    """
    normalized = {k.lower(): v for k, v in properties.items()}
    if len(normalized) != len(properties):
        fail("MSBuild property names must be unique ignoring case")
    return json.encode([framework, reference_framework, configuration, sorted(normalized.items())])
