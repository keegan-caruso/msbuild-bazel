"""Analysis-only selection of explicit framework variants."""

load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildProjectInfo")

def _framework(value):
    family = "standard" if value.startswith("netstandard") else "net"
    version = value.removeprefix("netstandard" if family == "standard" else "net").split(".")
    if len(version) != 2 or not all([v.isdigit() for v in version]):
        return None
    major, minor = [int(v) for v in version]
    if family == "standard":
        if (major != 1 or minor > 6) and (major != 2 or minor > 1):
            return None
    elif not value.startswith("net") or major < 5:
        return None
    return (family, major, minor)

def select_assembly(target, framework):
    """Return one assembly; unsupported fallback requires an explicit variant label.

    Args:
        target: An assembly or project facade dependency.
        framework: The consuming project's target framework.

    Returns:
        The selected MSBuildAssemblyInfo provider.
    """
    if MSBuildAssemblyInfo in target:
        return target[MSBuildAssemblyInfo]
    variants = target[MSBuildProjectInfo].variants
    if framework in variants:
        return variants[framework]
    consumer = _framework(framework)
    candidates = []
    if consumer:
        for tfm in variants:
            candidate = _framework(tfm)
            if not candidate:
                continue
            same_family = candidate[0] == consumer[0]
            if (same_family and candidate[1:] <= consumer[1:]) or (consumer[0] == "net" and candidate[0] == "standard"):
                candidates.append((1 if same_family else 0, candidate[1], candidate[2], tfm))
    if candidates:
        return variants[sorted(candidates)[-1][3]]
    fail("No supported framework selection for %s from %s; available: %s. Use an explicit variant label for other compatibility relationships." % (framework, target.label, ", ".join(sorted(variants))))

def _project_group(ctx):
    variants = {}
    projects = {}
    for target in ctx.attr.variants:
        info = target[MSBuildAssemblyInfo]
        if info.framework in variants:
            fail("Duplicate project framework: " + info.framework)
        variants[info.framework] = info
        projects[info.project] = True
    if len(projects) != 1:
        fail("A project facade requires variants of exactly one project")
    return [
        MSBuildProjectInfo(variants = variants),
        DefaultInfo(files = depset(transitive = [target[DefaultInfo].files for target in ctx.attr.variants])),
    ]

project_group = rule(
    implementation = _project_group,
    attrs = {"variants": attr.label_list(providers = [MSBuildAssemblyInfo], mandatory = True)},
)
