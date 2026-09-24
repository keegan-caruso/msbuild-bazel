"""Register explicit project build actions and outputs."""

load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN", _file = "input_file", _logical = "logical", _mapped_imports = "mapped_imports", _quote = "quote", _runfile = "runfile", _runtime_package = "runtime_package")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildBindingInfo", "MSBuildItemsInfo", "MSBuildLayoutInfo", "MSBuildPackageInfo", "MSBuildPackageLockInfo", "MSBuildProjectOutputInfo", "MSBuildReferencePackInfo", "MSBuildRestoreInfo", "MSBuildRuntimeInfo", "MSBuildTestToolInfo", "MSBuildToolInfo")

def _configuration(ctx):
    return ctx.attr.configuration or ("Debug" if ctx.var["COMPILATION_MODE"] == "dbg" else "Release")

def build_project(ctx, executable = False, test = False, restore_only = False, project = None, generate = False):
    """Register compilation or preparation and return the target providers.

    Args:
        ctx: Rule context containing explicit project inputs.
        executable: Whether to compile an executable assembly.
        test: Whether to create a test launcher.
        restore_only: Whether to export only shared restore metadata.
        project: Optional generated project file replacing ctx.file.project.
        generate: Whether to run declared generation targets.

    Returns:
        Default, assembly, restore or generated output providers.
    """
    if (executable or test) and ctx.attr.output_mode == "reference":
        fail("Reference-only projects cannot execute")
    project = project or ctx.file.project
    tc = ctx.toolchains[_TOOLCHAIN]
    name = ctx.attr.assembly_name or project.basename.removesuffix(".csproj")
    reference = ctx.actions.declare_file(ctx.label.name + ".restore.json" if restore_only else ctx.label.name + ".reference/" + name + ".dll") if not generate else None
    runtime = ctx.actions.declare_directory(ctx.label.name + ".runtime") if not generate else None
    identity = ctx.actions.declare_file(ctx.label.name + ".identity.json") if not generate and not restore_only else None
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    restore_project = ctx.actions.declare_file(ctx.label.name + ".restore-project.json") if not generate and not restore_only else None
    target_output = ctx.actions.declare_file(ctx.label.name + ".targets.json") if ctx.attr.export_targets else None
    if generate:
        if len(ctx.attr.outputs) != len(depset(ctx.attr.outputs).to_list()):
            fail("Duplicate generated output")
        for path in ctx.attr.outputs:
            if "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")]):
                fail("Generated outputs require safe relative paths")
    generated = {path: ctx.actions.declare_file(ctx.label.name + ".generated/" + path) for path in ctx.attr.outputs} if generate else {}
    if generate and (not generated or not ctx.attr.targets):
        fail("Generation requires explicit targets and outputs")
    items = []
    target_items = []
    for group in ctx.attr.items:
        items.extend(group[MSBuildItemsInfo].items)
        target_items.extend(group[MSBuildItemsInfo].target_items)
    direct = [dep[MSBuildAssemblyInfo] for dep in ctx.attr.deps if MSBuildAssemblyInfo in dep]
    if ctx.attr.output_mode != "reference" and any([dep.output_mode == "reference" for dep in direct]):
        fail("Reference-only dependencies require msbuild_assembly with an implementation")
    compile_targets = [dep for dep in ctx.attr.deps if MSBuildPackageInfo in dep] + ctx.attr.reference_packages
    compile_packages = depset([dep[MSBuildPackageInfo].id for dep in compile_targets], transitive = [dep.compile_packages for dep in direct])
    runtime_references = depset([dep.reference for dep in direct], transitive = [dep.runtime_references for dep in direct])
    restore_projects = depset([dep.restore_project for dep in direct], transitive = [dep.restore_projects for dep in direct])
    analyzer_packages = [dep for dep in ctx.attr.analyzers if MSBuildPackageInfo in dep]
    analyzer_projects = [dep[MSBuildAssemblyInfo] for dep in ctx.attr.analyzers if MSBuildAssemblyInfo in dep]
    build_tools = [target[MSBuildToolInfo] for target in ctx.attr.tools]
    bindings = []
    bound_names = {}
    for target in ctx.attr.bindings:
        binding = target[MSBuildBindingInfo]
        key = binding.property_name.lower()
        if key in bound_names:
            fail("Duplicate bound property: " + binding.property_name)
        bound_names[key] = True
        if binding.tool not in build_tools:
            fail("Bound tool must also be declared in tools: " + str(target.label))
        bindings.append({"property": binding.property_name, "tool": build_tools.index(binding.tool)})
    project_outputs = [dep[MSBuildProjectOutputInfo] for dep in ctx.attr.project_outputs]
    package_targets = compile_targets + ctx.attr.build_deps + analyzer_packages
    private_packages = {key.lower(): value.lower() for key, value in ctx.attr.package_private_assets.items()}
    direct_package_ids = {dep[MSBuildPackageInfo].id.lower(): True for dep in package_targets}
    for key, value in private_packages.items():
        if key not in direct_package_ids or value not in ["all", "none"]:
            fail("package_private_assets requires a direct package and all or none: " + key)
    exported_compile_packages = depset([dep[MSBuildPackageInfo].id for dep in compile_targets if private_packages.get(dep[MSBuildPackageInfo].id.lower(), "none") != "all"], transitive = [dep.compile_packages for dep in direct])
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
    if len({dep.project: True for dep in direct}) != len(direct):
        fail("Select exactly one configured compile dependency per project")
    framework_references = depset(ctx.attr.framework_refs, transitive = [dep.framework_references for dep in direct])
    pack = ctx.attr.reference_pack[MSBuildReferencePackInfo] if ctx.attr.reference_pack else None
    pack_files = pack.references if pack else depset()
    references = depset([dep.reference for dep in direct], transitive = [dep.references for dep in direct])
    if not ctx.attr.transitive_compile_references and (executable or test):
        fail("Direct-only compilation references are supported only for libraries")
    compiler_references = references if ctx.attr.transitive_compile_references else depset([dep.reference for dep in direct])
    runtimes = depset([dep.runtime for dep in direct], transitive = [dep.runtimes for dep in direct])
    data = []
    used = {}
    for target, destination in ctx.attr.data_paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("data_paths requires a single file per label")
        used[files[0].path] = destination
    data_files = depset(ctx.files.data + [file for target in ctx.attr.data_paths for file in target[DefaultInfo].files.to_list()]).to_list()
    for file in data_files:
        logical = _logical(file)
        prefix = ctx.label.package + "/" if ctx.label.package else ""
        destination = used.get(file.path, logical.removeprefix(prefix) if logical.startswith(prefix) else logical)
        data.append(struct(file = file, destination = destination))
    runtime_data = depset(data, transitive = [dep.runtime_data for dep in direct])
    package_directories = {file.path: file for file in package_files.to_list()}
    runtime_packages = depset([struct(id = row["id"], version = row["version"], directory = package_directories[row["directory"]]) for row in package_rows.values()], transitive = [dep.runtime_packages for dep in direct])
    restore = ctx.attr.restore[MSBuildRestoreInfo] if ctx.attr.restore else None
    if restore:
        if restore.framework != ctx.attr.target_framework or restore.configuration != _configuration(ctx) or restore.executable != executable:
            fail("Shared restore framework/configuration/output kind must match the assembly")
        if ctx.attr.reference_pack or ctx.attr.layout_bindings or ctx.attr.output_mode != "sdk" or package_rows or ctx.attr.msbuild_imports or ctx.attr.import_paths or ctx.attr.adapter_imports or framework_references.to_list():
            fail("Shared restore currently requires package-free projects without imports or framework_refs")
    compile_names = {file.basename: True for file in compiler_references.to_list()}
    runtime_only_references = depset([file for file in runtime_references.to_list() if file.basename not in compile_names]) if executable or test else depset()
    dependency_properties = {}
    for dep in direct + analyzer_projects + [p.assembly for p in project_outputs]:
        properties = dict(dep.properties, Configuration = dep.configuration, TargetFramework = dep.framework)
        if dep.project in dependency_properties and dependency_properties[dep.project] != properties:
            fail("Select one configuration per dependency project: " + dep.project)
        dependency_properties[dep.project] = properties
    for tool in build_tools:
        if tool.native:
            continue
        if tool.project in dependency_properties and dependency_properties[tool.project] != tool.properties:
            fail("Select one configuration per dependency project: " + tool.project)
        dependency_properties[tool.project] = tool.properties
    ctx.actions.write(request, json.encode({
        "profileBuild": ctx.attr.profile_build,
        "restoreInput": restore.file.path if restore else None,
        "restoreOnly": restore_only,
        "restoreProjectOutput": restore_project.path if restore_project else None,
        "restoreProjects": [file.path for file in restore_projects.to_list()],
        "project": _file(project),
        "sources": [_file(file) for file in ctx.files.srcs],
        "directories": ctx.attr.directories,
        "imports": [_file(file) for file in ctx.files.msbuild_imports] + _mapped_imports(ctx),
        "referencePackages": [dep[MSBuildPackageInfo].id for dep in ctx.attr.reference_packages],
        "packageReferencePaths": ctx.attr.package_reference_paths,
        "generateTargets": ctx.attr.targets if generate else [],
        "generatedOutputs": {path: file.path for path, file in generated.items()},
        "outputProperties": ctx.attr.output_properties if generate else {},
        "adapterImports": [_file(file) for file in ctx.files.adapter_imports],
        "items": items,
        "targetInputs": target_items,
        "targetExports": ctx.attr.export_targets,
        "targetOutput": target_output.path if target_output else None,
        "dependencies": [dep.project for dep in direct],
        "dependencyFrameworks": {dep.project: dep.reference_framework for dep in direct},
        "dependencyRestoreKeys": {dep.project: dep.restore_key for dep in direct},
        "runtimeReferences": [file.path for file in runtime_only_references.to_list()],
        "dependencyProperties": dependency_properties,
        "outputMode": ctx.attr.output_mode,
        "identityOutput": identity.path if identity else None,
        "frameworkInputs": [file.path for file in pack_files.to_list()] if pack else None,
        "layoutBindings": [{"directory": target[MSBuildLayoutInfo].directory.path, "property": prop} for target, prop in ctx.attr.layout_bindings.items()],
        "references": [file.path for file in compiler_references.to_list()],
        "framework": ctx.attr.target_framework,
        "frameworkReferences": framework_references.to_list(),
        "frameworkAssemblies": ctx.attr.framework_assemblies,
        "projectOutputs": [{"project": p.assembly.project, "assembly": p.assembly.reference.basename, "directory": p.assembly.runtime.path if p.artifact == "implementation" else None, "file": p.assembly.reference.path if p.artifact == "reference" else None, "type": p.item_type, "metadata": p.metadata} for p in project_outputs],
        "assembly": name,
        "executable": executable,
        "useAppHost": ctx.attr.use_apphost,
        "configuration": _configuration(ctx),
        "properties": dict(ctx.attr.msbuild_properties, GenerateRuntimeConfigurationFiles = "true") if test and ctx.attr.test_protocol == "vstest" else ctx.attr.msbuild_properties,
        "packages": package_rows.values(),
        "compilePackages": compile_packages.to_list(),
        "packagePrivateAssets": private_packages,
        "declaredPackages": [dep[MSBuildPackageInfo].id for dep in package_targets],
        "buildPackages": [row["id"] for dep in ctx.attr.build_deps for row in dep[MSBuildPackageInfo].rows],
        "analyzerPackages": [row["id"] for dep in analyzer_packages for row in dep[MSBuildPackageInfo].rows],
        "buildTools": [{"native": dep.native, "layoutPrefix": dep.layout_prefix, "project": dep.project, "entryPoint": dep.entry_point, "directories": [file.path for file in dep.directories.to_list()], "packages": [_runtime_package(row) for row in dep.packages.to_list()], "data": [{"source": row.file.path, "path": row.destination} for row in dep.data]} for dep in build_tools],
        "fileBindings": bindings,
        "projectAnalyzers": [{"project": dep.project, "assembly": dep.reference.basename, "directories": [dep.runtime.path] + [file.path for file in dep.runtimes.to_list()], "packages": [_runtime_package(row) for row in dep.runtime_packages.to_list()]} for dep in analyzer_projects],
        "defines": ctx.attr.defines,
        "nullable": ctx.attr.nullable,
        "languageVersion": ctx.attr.lang_version,
        "allowUnsafe": ctx.attr.allow_unsafe,
        "runtime": runtime.path if runtime else diagnostics.path,
        "reference": reference.path if reference else diagnostics.path,
        "diagnostics": diagnostics.path,
        "sdkVersion": tc.sdk_version,
        "runtimeManifest": tc.runtime_manifest.path,
    }))
    arguments = [tc.runner.path, "build", request.path]
    requirements = {"no-sandbox": "1"}
    if not ctx.attr.allow_remote_execution:
        requirements["no-remote-exec"] = "1"
    if ctx.attr.linux_worker:
        params = ctx.actions.args()
        params.add(request.path)
        params.use_param_file("@%s", use_always = True)
        params.set_param_file_format("multiline")
        arguments = [tc.runner.path, "--bazel-worker", "--tool-inputs=" + tc.worker_tools.path, params]
        requirements.update({"supports-workers": "1", "requires-worker-protocol": "json"})
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = arguments,
        tools = depset([tc.runner, tc.worker_tools], transitive = [tc.sdk, tc.runner_support]) if ctx.attr.linux_worker else [],
        inputs = depset(
            [project, request, tc.runner, tc.runtime_manifest] + ctx.files.srcs + ctx.files.msbuild_imports + ctx.files.import_paths + ctx.files.adapter_imports + ([restore.file] if restore else []),
            transitive = [depset([p.assembly.reference if p.artifact == "reference" else p.assembly.runtime for p in project_outputs]), depset([dep.runtime for dep in analyzer_projects] + [row.directory for dep in analyzer_projects for row in dep.runtime_packages.to_list()], transitive = [dep.runtimes for dep in analyzer_projects]), tc.sdk, tc.runner_support, compiler_references, runtime_only_references, pack_files, depset([target[MSBuildLayoutInfo].directory for target in ctx.attr.layout_bindings]), package_files, restore_projects] + [group[MSBuildItemsInfo].files for group in ctx.attr.items] + [tool.files for tool in build_tools],
        ),
        outputs = ([diagnostics] + generated.values()) if generate else [reference, runtime, diagnostics] + ([identity] if identity else []) + ([restore_project] if restore_project else []) + ([target_output] if target_output else []),
        mnemonic = "MSBuildGenerate" if generate else "MSBuildRestore" if restore_only else "MSBuildAssembly",
        env = {"LANG": "en_US.UTF-8"},
        # The runner stages only declared files and starts a deny-by-default
        # child sandbox. macOS does not permit nested sandbox-exec.
        execution_requirements = requirements,
    )
    if generate:
        return [DefaultInfo(files = depset(generated.values())), OutputGroupInfo(**{name: depset([file]) for name, file in generated.items()})]
    if restore_only:
        return [DefaultInfo(files = depset([reference])), MSBuildRestoreInfo(file = reference, framework = ctx.attr.target_framework, configuration = _configuration(ctx), executable = executable)]
    info = MSBuildAssemblyInfo(
        project = _logical(project),
        framework = ctx.attr.target_framework,
        reference_framework = ctx.attr.target_framework,
        restore_key = ctx.attr.target_framework + "/" + ctx.attr.target_framework,
        configuration = _configuration(ctx),
        properties = ctx.attr.msbuild_properties,
        assembly = name,
        output_mode = ctx.attr.output_mode,
        identity = identity,
        reference = reference,
        references = references,
        runtime_references = runtime_references,
        runtime = runtime,
        runtimes = runtimes,
        packages = package_rows.values(),
        package_files = package_files,
        compile_packages = exported_compile_packages,
        restore_project = restore_project,
        restore_projects = restore_projects,
        runtime_data = runtime_data,
        runtime_packages = runtime_packages,
        target_output = target_output,
        export_targets = ctx.attr.export_targets,
        framework_references = framework_references,
    )
    if not executable and not test:
        return [DefaultInfo(files = depset([runtime])), info, OutputGroupInfo(reference = depset([reference]), diagnostics = depset([diagnostics]), target_results = depset([target_output] if target_output else []))]
    test_tools = ([ctx.attr.test_runner] if ctx.attr.test_runner else []) + ctx.attr.test_adapters if test else []
    def_tool = None
    if test and ctx.attr.test_runner:
        def_tool = ctx.attr.test_runner[MSBuildTestToolInfo]
    host = ctx.attr.runtime_host[MSBuildRuntimeInfo] if ctx.attr.runtime_host else None
    launch_request = ctx.actions.declare_file(ctx.label.name + ".launch.json")
    ctx.actions.write(launch_request, json.encode({
        "runtimeHost": {"directory": _runfile(ctx, host.directory), "entryPoint": host.entry_point} if host else None,
        "entry": _runfile(ctx, runtime),
        "packages": [_runtime_package(row, ctx) for row in runtime_packages.to_list()],
        "dependencies": [_runfile(ctx, file) for file in runtimes.to_list()],
        "assembly": name,
        "test": test,
        "testOptions": {
            "protocol": ctx.attr.test_protocol,
            "settings": _runfile(ctx, ctx.file.test_settings) if ctx.file.test_settings else None,
            "settingsOutput": ctx.attr.test_settings_output or None,
            "filterArgument": ctx.attr.test_filter_argument,
            "allowEmpty": ctx.attr.allow_empty_tests,
            "diagnostics": ctx.attr.test_diagnostics,
            "outputDirectories": ctx.attr.test_output_dirs,
            "runner": _runfile(ctx, def_tool.directory) + "/" + def_tool.path if def_tool else None,
            "adapters": [_runfile(ctx, tool[MSBuildTestToolInfo].directory) + "/" + tool[MSBuildTestToolInfo].path for tool in ctx.attr.test_adapters],
        } if test else None,
        "data": [{"source": _runfile(ctx, row.file), "path": row.destination} for row in runtime_data.to_list()],
    }))
    launcher = ctx.actions.declare_file(ctx.label.name)
    script = """#!/usr/bin/env bash
set -euo pipefail
runfiles="${RUNFILES_DIR:-${TEST_SRCDIR:-$0.runfiles}}"
export RULES_MSBUILD_RUNFILES="$runfiles"
exec "$runfiles/"%s "$runfiles/"%s run "$runfiles/"%s "$@"
""" % (_quote(_runfile(ctx, tc.dotnet)), _quote(_runfile(ctx, tc.runner)), _quote(_runfile(ctx, launch_request)))
    ctx.actions.write(launcher, script, is_executable = True)
    runfiles = ctx.runfiles(
        files = [tc.dotnet, tc.runner, runtime, launch_request] + ([host.directory] if host else []) + [row.file for row in runtime_data.to_list()] + ([ctx.file.test_settings] if test and ctx.file.test_settings else []),
        transitive_files = depset(transitive = [tc.sdk, tc.runner_support, runtimes, depset([row.directory for row in runtime_packages.to_list()])] + [tool[MSBuildTestToolInfo].files for tool in test_tools]),
    )
    return ([RunEnvironmentInfo(environment = ctx.attr.env)] if test else []) + [DefaultInfo(executable = launcher, files = depset([runtime]), runfiles = runfiles), info, OutputGroupInfo(reference = depset([reference]), diagnostics = depset([diagnostics]), target_results = depset([target_output] if target_output else []))]
