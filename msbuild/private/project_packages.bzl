"""Resolve the locked package inputs for an explicit project action."""

load(":providers.bzl", "MSBuildPackageInfo", "MSBuildPackageLockInfo")

def resolve_packages(ctx, public, direct, compile_targets, analyzer_packages):
    """Validate package assets and return the direct and exported closures.

    Args:
        ctx: Project rule context.
        public: Public assembly dependencies.
        direct: Public and implementation assembly dependencies.
        compile_targets: Direct package compile references.
        analyzer_packages: Package targets that provide analyzers.

    Returns:
        Package targets, asset masks, rows, files and compile closures.
    """
    compile_packages = depset([dep[MSBuildPackageInfo].id for dep in compile_targets], transitive = [dep.compile_packages for dep in direct])
    package_targets = compile_targets + ctx.attr.build_deps + analyzer_packages
    private_packages = {key.lower(): value.lower() for key, value in ctx.attr.package_private_assets.items()}
    direct_package_ids = {dep[MSBuildPackageInfo].id.lower(): True for dep in package_targets}
    for key, value in private_packages.items():
        if key not in direct_package_ids or any([part.strip() not in ["all", "none", "compile", "runtime", "native", "contentfiles", "analyzers", "build", "buildtransitive", "buildmultitargeting"] for part in value.split(";")]):
            fail("package_private_assets requires a direct package and a valid asset mask: " + key)
    exported_compile_packages = depset([dep[MSBuildPackageInfo].id for dep in compile_targets if private_packages.get(dep[MSBuildPackageInfo].id.lower(), "none") != "all"], transitive = [dep.compile_packages for dep in public])
    package_rows = {}
    for dep in package_targets:
        for row in dep[MSBuildPackageInfo].rows:
            key = row["id"].lower()
            if key in package_rows and package_rows[key] != row:
                fail("Conflicting locked package: " + key)
            package_rows[key] = row
    if ctx.attr.package_lock:
        lock = ctx.attr.package_lock[MSBuildPackageLockInfo]
        locked = {row["id"].lower(): row for row in lock.rows}
        if len(locked) != len(lock.rows):
            fail("Per-project package_lock requires one version per package ID")
        for key, row in package_rows.items():
            if locked.get(key) != row:
                fail("Direct package closure disagrees with package_lock: " + key)
        package_rows = locked
        compile_packages = depset([name for name in compile_packages.to_list() if name.lower() in locked])
        exported_compile_packages = depset([name for name in exported_compile_packages.to_list() if name.lower() in locked])
        package_files = lock.files
    else:
        for dep in direct:
            for row in dep.packages:
                key = row["id"].lower()
                if key in package_rows and package_rows[key] != row:
                    fail("Conflicting inherited package: " + key)
                package_rows[key] = row
        package_files = depset(transitive = [dep[MSBuildPackageInfo].files for dep in package_targets] + [dep.package_files for dep in direct])
    return struct(
        targets = package_targets,
        private_assets = private_packages,
        rows = package_rows,
        files = package_files,
        compile = compile_packages,
        exported_compile = exported_compile_packages,
    )
