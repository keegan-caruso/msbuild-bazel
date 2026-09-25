"""Pair reference contracts with runtime implementations."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")
load(":providers.bzl", "MSBuildAssemblyInfo")
load(":selection.bzl", "restore_key")

def _assembly(ctx):
    contract = ctx.attr.contract[MSBuildAssemblyInfo]
    implementation = ctx.attr.implementation[MSBuildAssemblyInfo]
    if implementation.output_mode == "reference":
        fail("An assembly implementation cannot be reference-only")

    # An explicitly paired platform implementation may implement a neutral
    # contract for the same base framework. Platform-to-platform and reverse
    # substitutions still require exact framework equality.
    compatible = contract.framework == implementation.framework or ("-" not in contract.framework and implementation.framework.startswith(contract.framework + "-"))
    if contract.assembly != implementation.assembly or not compatible:
        fail("Contract and implementation assembly name/framework must match")
    packages = {}
    for row in contract.packages + implementation.packages:
        key = row["id"].lower()
        if key in packages and packages[key] != row:
            fail("Conflicting contract/implementation package: " + key)
        packages[key] = row
    key = restore_key(implementation.framework, contract.reference_framework, implementation.configuration, implementation.properties)
    tc = ctx.toolchains[_TOOLCHAIN]
    reference_source = implementation.reference if ctx.attr.use_implementation_reference else contract.reference
    reference = ctx.actions.declare_file(ctx.label.name + ".reference/" + contract.assembly + ".dll")
    restore_project = ctx.actions.declare_file(ctx.label.name + ".restore-project.json")
    request = ctx.actions.declare_file(ctx.label.name + ".pair.json")
    ctx.actions.write(request, json.encode({"contract": reference_source.path, "contractIdentity": contract.identity.path, "implementationIdentity": implementation.identity.path, "output": reference.path, "contractRestore": contract.restore_project.path, "implementationRestore": implementation.restore_project.path, "restoreOutput": restore_project.path, "restoreKey": key}))
    ctx.actions.run(executable = tc.dotnet, arguments = [tc.runner.path, "pair", request.path], inputs = depset([request, tc.runner, reference_source, contract.identity, implementation.identity, contract.restore_project, implementation.restore_project], transitive = [tc.sdk, tc.runner_support]), outputs = [reference, restore_project], mnemonic = "MSBuildAssemblyPair")
    return [DefaultInfo(files = depset([implementation.runtime, reference])), MSBuildAssemblyInfo(
        selections = depset(transitive = [contract.selections, implementation.selections]),
        dependency_nodes = depset(transitive = [contract.dependency_nodes, implementation.dependency_nodes]),
        project = implementation.project,
        framework = implementation.framework,
        reference_framework = contract.reference_framework,
        restore_key = key,
        configuration = implementation.configuration,
        properties = implementation.properties,
        assembly = implementation.assembly,
        output_mode = "paired",
        identity = implementation.identity,
        reference = reference,
        references = implementation.references if ctx.attr.use_implementation_reference else contract.references,
        runtime_references = implementation.runtime_references,
        runtime = implementation.runtime,
        runtimes = implementation.runtimes,
        packages = packages.values(),
        package_files = depset(transitive = [contract.package_files, implementation.package_files]),
        compile_packages = contract.compile_packages,
        runtime_data = implementation.runtime_data,
        runtime_packages = implementation.runtime_packages,
        target_output = implementation.target_output,
        export_targets = implementation.export_targets,
        framework_references = contract.framework_references,
        restore_project = restore_project,
        restore_projects = implementation.restore_projects,
    )]

msbuild_assembly = rule(
    implementation = _assembly,
    attrs = {
        "contract": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo]),
        "implementation": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo]),
        "use_implementation_reference": attr.bool(default = False),
    },
    toolchains = [_TOOLCHAIN],
)
