"""Explicit project graph, generic MSBuild items, and executable tests."""

_TOOLCHAIN = Label("//msbuild:toolchain_type")

MSBuildRestoreInfo = provider("Qualified SDK restore metadata shared by matching projects.", fields = ["file", "framework", "configuration", "executable"])

MSBuildPackageInfo = provider("Locked package extraction and dependency closure.", fields = ["id", "version", "directory", "rows", "files"])

MSBuildPackageLockInfo = provider("Explicit per-project resolved package set.", fields = ["rows", "files"])

MSBuildAssemblyInfo = provider("Reference assembly and separate runtime dependency closure.", fields = ["project", "framework", "reference_framework", "restore_key", "configuration", "properties", "assembly", "output_mode", "identity", "reference", "references", "runtime_references", "runtime", "runtimes", "packages", "package_files", "compile_packages", "runtime_data", "runtime_packages", "target_output", "export_targets", "framework_references", "restore_project", "restore_projects"])

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
    tc = ctx.toolchains[_TOOLCHAIN]
    reference_source = implementation.reference if ctx.attr.use_implementation_reference else contract.reference
    reference = ctx.actions.declare_file(ctx.label.name + ".reference/" + contract.assembly + ".dll")
    restore_project = ctx.actions.declare_file(ctx.label.name + ".restore-project.json")
    request = ctx.actions.declare_file(ctx.label.name + ".pair.json")
    ctx.actions.write(request, json.encode({"contract": reference_source.path, "contractIdentity": contract.identity.path, "implementationIdentity": implementation.identity.path, "output": reference.path, "contractRestore": contract.restore_project.path, "implementationRestore": implementation.restore_project.path, "restoreOutput": restore_project.path}))
    ctx.actions.run(executable = tc.dotnet, arguments = [tc.runner.path, "pair", request.path], inputs = depset([request, tc.runner, reference_source, contract.identity, implementation.identity, contract.restore_project, implementation.restore_project], transitive = [tc.sdk, tc.runner_support]), outputs = [reference, restore_project], mnemonic = "MSBuildAssemblyPair")
    return [DefaultInfo(files = depset([implementation.runtime, reference])), MSBuildAssemblyInfo(
        project = implementation.project,
        framework = implementation.framework,
        reference_framework = contract.reference_framework,
        restore_key = implementation.framework + "/" + contract.reference_framework,
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

MSBuildItemsInfo = provider("Explicit MSBuild items with declared files and metadata.", fields = ["items", "files", "target_items"])
MSBuildLayoutInfo = provider("A composed artifact tree with explicit destinations.", fields = ["directory"])
MSBuildRuntimeInfo = provider("Runtime host and its complete declared tree.", fields = ["directory", "entry_point"])
MSBuildReferencePackInfo = provider("Explicit compile-only framework assemblies.", fields = ["references"])

MSBuildToolInfo = provider("Build-time implementation closure in the execution configuration.", fields = ["project", "entry_point", "directories", "packages", "data", "files", "native", "properties", "layout_prefix"])
MSBuildBindingInfo = provider("Declared task property bound to a tool artifact.", fields = ["tool", "property_name"])

MSBuildTestToolInfo = provider("An explicit entry point or adapter directory in a locked package.", fields = ["directory", "path", "files"])

def _test_tool(ctx):
    path = ctx.attr.path
    if path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")]):
        fail("Test tool path must be a safe relative path")
    package = ctx.attr.package[MSBuildPackageInfo]
    return [DefaultInfo(files = package.files), MSBuildTestToolInfo(directory = package.directory, path = path, files = package.files)]

msbuild_test_tool = rule(
    implementation = _test_tool,
    attrs = {
        "package": attr.label(mandatory = True, providers = [MSBuildPackageInfo]),
        "path": attr.string(mandatory = True),
    },
)

MSBuildProjectOutputInfo = provider("Selected project assembly consumed as an MSBuild content item.", fields = ["assembly", "item_type", "metadata", "artifact"])

def _project_output(ctx):
    assembly = ctx.attr.assembly[MSBuildAssemblyInfo]
    return [DefaultInfo(files = depset([assembly.reference if ctx.attr.artifact == "reference" else assembly.runtime])), MSBuildProjectOutputInfo(assembly = assembly, item_type = ctx.attr.item_type, metadata = ctx.attr.metadata, artifact = ctx.attr.artifact)]

msbuild_project_output = rule(
    implementation = _project_output,
    attrs = {
        "assembly": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo]),
        "item_type": attr.string(mandatory = True),
        "artifact": attr.string(default = "implementation", values = ["implementation", "reference"]),
        "metadata": attr.string_dict(),
    },
)

def _tool(ctx):
    info = ctx.attr.assembly[MSBuildAssemblyInfo]
    entry = ctx.attr.entry_point or info.reference.basename
    if entry.startswith("/") or "\\" in entry or any([part in ["", ".", ".."] for part in entry.split("/")]):
        fail("Tool entry_point must be a safe relative file path")
    prefix = ctx.attr.layout_prefix
    if prefix and (prefix.startswith("/") or "\\" in prefix or any([part in ["", ".", ".."] for part in prefix.split("/")])):
        fail("Tool layout_prefix must be a safe relative path")
    if prefix:
        entry = prefix + "/" + entry
    directories = depset([info.runtime], transitive = [info.runtimes])
    data = info.runtime_data.to_list()
    files = depset([row.file for row in data], transitive = [directories, depset([row.directory for row in info.runtime_packages.to_list()])])
    return [DefaultInfo(files = files), MSBuildToolInfo(native = False, layout_prefix = prefix, properties = dict(info.properties, Configuration = info.configuration, TargetFramework = info.framework), project = info.project, entry_point = entry, directories = directories, packages = info.runtime_packages, data = data, files = files)]

msbuild_tool = rule(
    implementation = _tool,
    attrs = {
        "assembly": attr.label(mandatory = True, providers = [MSBuildAssemblyInfo], cfg = "exec"),
        "entry_point": attr.string(),
        "layout_prefix": attr.string(),
    },
)

def _binding(ctx):
    tool = ctx.attr.tool[MSBuildToolInfo]
    return [DefaultInfo(files = tool.files), MSBuildBindingInfo(tool = tool, property_name = ctx.attr.property_name)]

msbuild_file_binding = rule(
    implementation = _binding,
    attrs = {
        "tool": attr.label(mandatory = True, providers = [MSBuildToolInfo]),
        "property_name": attr.string(mandatory = True),
    },
)

def _runtime_package(row, ctx = None):
    return {"id": row.id, "version": row.version, "directory": _runfile(ctx, row.directory) if ctx else row.directory.path}

def _logical(file):
    path = file.short_path
    if path.startswith("../"):
        # Keep repository identities in the logical namespace.
        return "external/" + path[3:]
    return path

def _file(file):
    return {"source": file.path, "path": _logical(file)}

def _mapped_imports(ctx):
    rows = []
    for target, path in ctx.attr.import_paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("import_paths requires one file per label")
        rows.append({"source": files[0].path, "path": path})
    return rows

def _items(ctx):
    rows = [{"type": ctx.attr.item_type, "file": _file(file), "metadata": ctx.attr.metadata} for file in ctx.files.srcs]
    return [DefaultInfo(files = depset(ctx.files.srcs)), MSBuildItemsInfo(items = rows, files = depset(ctx.files.srcs), target_items = [])]

msbuild_items = rule(
    implementation = _items,
    attrs = {
        "item_type": attr.string(mandatory = True),
        "srcs": attr.label_list(allow_files = True),
        "metadata": attr.string_dict(),
    },
)

def _target_items(ctx):
    files = []
    rows = []
    for dep in ctx.attr.deps:
        info = dep[MSBuildAssemblyInfo]
        if ctx.attr.target not in info.export_targets:
            fail("MSBuild target is not exported: " + ctx.attr.target)
        files.append(info.target_output)
        rows.append({"file": info.target_output.path, "target": ctx.attr.target, "type": ctx.attr.item_type, "beforeTargets": ctx.attr.before_targets})
    return [DefaultInfo(files = depset(files)), MSBuildItemsInfo(items = [], files = depset(files), target_items = rows)]

msbuild_target_items = rule(
    implementation = _target_items,
    attrs = {
        "deps": attr.label_list(providers = [MSBuildAssemblyInfo]),
        "target": attr.string(mandatory = True),
        "item_type": attr.string(mandatory = True),
        "before_targets": attr.string_list(),
    },
)

def _quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"

def _runfile(ctx, file):
    if file.short_path.startswith("../"):
        return file.short_path[3:]
    return ctx.workspace_name + "/" + file.short_path

def _configuration(ctx):
    return ctx.attr.configuration or ("Debug" if ctx.var["COMPILATION_MODE"] == "dbg" else "Release")

def _project(ctx, executable = False, test = False, restore_only = False, project = None, generate = False):
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

def _library(ctx):
    return _project(ctx)

def _binary(ctx):
    return _project(ctx, executable = True)

def _test(ctx):
    if ctx.attr.test_settings and ctx.attr.test_settings_output:
        fail("Declare either test_settings or test_settings_output")
    path = ctx.attr.test_settings_output
    if path and (path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")])):
        fail("test_settings_output must be a safe relative path")
    if ctx.attr.shard_count > 1:
        fail("Executable tests do not yet support sharding")
    if ctx.attr.test_diagnostics and ctx.attr.test_protocol != "vstest":
        fail("test_diagnostics currently requires VSTest")
    if ctx.attr.test_protocol == "vstest":
        if not ctx.attr.test_runner:
            fail("VSTest requires an explicit test_runner")
        if ctx.attr.test_filter_argument:
            fail("VSTest uses TestCaseFilter syntax; test_filter_argument is only for MTP")
    elif ctx.attr.test_runner or ctx.attr.test_adapters:
        fail("test_runner and test_adapters are only supported by VSTest")
    return _project(ctx, executable = ctx.attr.test_protocol != "vstest" or ctx.attr.test_output_type == "exe", test = True)

_ATTRS = {
    "runtime_host": attr.label(providers = [MSBuildRuntimeInfo]),
    "reference_pack": attr.label(providers = [MSBuildReferencePackInfo]),
    "layout_bindings": attr.label_keyed_string_dict(providers = [MSBuildLayoutInfo]),
    "configuration": attr.string(),
    "output_mode": attr.string(default = "sdk", values = ["sdk", "reference", "implementation"]),
    "linux_worker": attr.bool(default = False),
    "allow_remote_execution": attr.bool(default = False),
    "profile_build": attr.bool(default = False),
    "restore": attr.label(providers = [MSBuildRestoreInfo]),
    "project": attr.label(allow_single_file = [".csproj"], mandatory = True),
    "target_framework": attr.string(mandatory = True),
    "assembly_name": attr.string(),
    "srcs": attr.label_list(allow_files = True),
    "directories": attr.string_list(),
    "items": attr.label_list(providers = [MSBuildItemsInfo]),
    "export_targets": attr.string_list_dict(),
    "deps": attr.label_list(providers = [[MSBuildAssemblyInfo], [MSBuildPackageInfo]]),
    "transitive_compile_references": attr.bool(default = True),
    "tools": attr.label_list(providers = [MSBuildToolInfo], cfg = "exec"),
    "project_outputs": attr.label_list(providers = [MSBuildProjectOutputInfo]),
    "bindings": attr.label_list(providers = [MSBuildBindingInfo], cfg = "exec"),
    "build_deps": attr.label_list(providers = [MSBuildPackageInfo]),
    "package_private_assets": attr.string_dict(),
    "package_lock": attr.label(providers = [MSBuildPackageLockInfo]),
    "analyzers": attr.label_list(providers = [[MSBuildPackageInfo], [MSBuildAssemblyInfo]]),
    "framework_refs": attr.string_list(),
    "framework_assemblies": attr.string_list(),
    "package_reference_paths": attr.string_list_dict(),
    "msbuild_imports": attr.label_list(allow_files = True),
    "import_paths": attr.label_keyed_string_dict(allow_files = True),
    "reference_packages": attr.label_list(providers = [MSBuildPackageInfo]),
    "adapter_imports": attr.label_list(allow_files = [".targets"]),
    "msbuild_properties": attr.string_dict(),
    "defines": attr.string_list(),
    "nullable": attr.string(default = "enable", values = ["enable", "disable", "warnings", "annotations"]),
    "lang_version": attr.string(default = "default"),
    "allow_unsafe": attr.bool(),
    "use_apphost": attr.bool(default = True),
    "data": attr.label_list(allow_files = True),
    "data_paths": attr.label_keyed_string_dict(allow_files = True),
}

msbuild_library = rule(implementation = _library, attrs = _ATTRS, toolchains = [_TOOLCHAIN])
msbuild_binary = rule(implementation = _binary, attrs = _ATTRS, toolchains = [_TOOLCHAIN], executable = True)
_TEST_ATTRS = dict(_ATTRS, **{
    "test_protocol": attr.string(default = "executable", values = ["executable", "mtp", "vstest"]),
    "test_settings": attr.label(allow_single_file = True),
    "test_settings_output": attr.string(),
    "test_filter_argument": attr.string(values = ["", "--filter", "--filter-query"]),
    "allow_empty_tests": attr.bool(),
    "env": attr.string_dict(),
    "test_diagnostics": attr.bool(),
    "test_output_type": attr.string(default = "library", values = ["library", "exe"]),
    "test_output_dirs": attr.string_list(),
    "test_runner": attr.label(providers = [MSBuildTestToolInfo]),
    "test_adapters": attr.label_list(providers = [MSBuildTestToolInfo]),
})
msbuild_test = rule(implementation = _test, attrs = _TEST_ATTRS, toolchains = [_TOOLCHAIN], test = True)

def _generate(ctx):
    if ctx.attr.restore or ctx.attr.export_targets:
        fail("Generation cannot use shared restore or assembly target exports")
    return _project(ctx, generate = True)

msbuild_generate = rule(
    implementation = _generate,
    attrs = dict(_ATTRS, targets = attr.string_list(mandatory = True), outputs = attr.string_list(mandatory = True), output_properties = attr.string_dict()),
    toolchains = [_TOOLCHAIN],
)

# Lower-level locked package target. Repository generation can emit these from
# a checked-in lock without making version-resolution decisions during builds.

def _package(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    output = ctx.actions.declare_directory(ctx.label.name + ".package")
    request = ctx.actions.declare_file(ctx.label.name + ".package.json")
    ctx.actions.write(request, json.encode({"id": ctx.attr.package_id, "version": ctx.attr.version, "archive": ctx.file.archive.path, "contentHash": ctx.attr.content_hash, "archiveSha256": ctx.attr.archive_sha256, "output": output.path}))
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "extract", request.path],
        inputs = depset([ctx.file.archive, request, tc.runner], transitive = [tc.runtime, tc.runner_support]),
        outputs = [output],
        mnemonic = "MSBuildNugetExtract",
        env = {"LANG": "en_US.UTF-8"},
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    rows = {ctx.attr.package_id.lower(): {"id": ctx.attr.package_id, "version": ctx.attr.version, "directory": output.path}}
    for dep in ctx.attr.deps:
        for row in dep[MSBuildPackageInfo].rows:
            if row["id"].lower() in rows and rows[row["id"].lower()] != row:
                fail("Conflicting locked package: " + row["id"])
            rows[row["id"].lower()] = row
    files = depset([output], transitive = [dep[MSBuildPackageInfo].files for dep in ctx.attr.deps])
    return [DefaultInfo(files = files), MSBuildPackageInfo(id = ctx.attr.package_id, version = ctx.attr.version, directory = output, rows = rows.values(), files = files)]

msbuild_nuget_package = rule(implementation = _package, attrs = {
    "package_id": attr.string(mandatory = True),
    "version": attr.string(mandatory = True),
    "archive": attr.label(allow_single_file = [".nupkg"], mandatory = True),
    "content_hash": attr.string(mandatory = True),
    "archive_sha256": attr.string(mandatory = True),
    "deps": attr.label_list(providers = [MSBuildPackageInfo]),
}, toolchains = [_TOOLCHAIN])

def _restore(ctx):
    if ctx.attr.export_targets:
        fail("Restore-only rules cannot export build target results")
    project = ctx.actions.declare_file(ctx.label.name + "/BazelRestore.csproj")
    ctx.actions.write(project, '<Project Sdk="Microsoft.NET.Sdk" />')
    return _project(ctx, executable = ctx.attr.executable, restore_only = True, project = project)

_RESTORE_ATTRS = dict(_ATTRS)
_RESTORE_ATTRS.pop("project")
_RESTORE_ATTRS["executable"] = attr.bool()
msbuild_restore = rule(implementation = _restore, attrs = _RESTORE_ATTRS, toolchains = [_TOOLCHAIN])

def _package_union(infos):
    rows = {}
    for info in infos:
        for row in info.rows:
            key = row["id"].lower()
            if key in rows and rows[key] != row:
                fail("Conflicting package set: " + key)
            rows[key] = row
    return rows.values(), depset(transitive = [info.files for info in infos])

def _package_dependencies(ctx):
    package = ctx.attr.package[MSBuildPackageInfo]
    rows, files = _package_union([package] + [dep[MSBuildPackageInfo] for dep in ctx.attr.deps])
    return [DefaultInfo(files = files), MSBuildPackageInfo(id = package.id, version = package.version, directory = package.directory, rows = rows, files = files)]

msbuild_nuget_dependencies = rule(implementation = _package_dependencies, attrs = {
    "package": attr.label(providers = [MSBuildPackageInfo], mandatory = True),
    "deps": attr.label_list(providers = [MSBuildPackageInfo]),
})

def _package_lock(ctx):
    rows, files = _package_union([dep[MSBuildPackageInfo] for dep in ctx.attr.packages])
    return [DefaultInfo(files = files), MSBuildPackageLockInfo(rows = rows, files = files)]

msbuild_package_lock = rule(implementation = _package_lock, attrs = {
    "packages": attr.label_list(providers = [MSBuildPackageInfo]),
})

def _layout(ctx):
    tc = ctx.toolchains[_TOOLCHAIN]
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    request = ctx.actions.declare_file(ctx.label.name + ".layout.json")
    rows = []
    for target, path in ctx.attr.paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1:
            fail("Layout paths require exactly one file or directory per label")
        rows.append({"source": files[0].path, "path": path})
    ctx.actions.write(request, json.encode({"files": rows, "output": output.path}))

    # Inspect the actual producer tree: Linux sandbox input trees contain synthetic
    # file symlinks, indistinguishable from forbidden links in a producer output.
    # Composition still reads only declared inputs and remains remotely cacheable.
    ctx.actions.run(executable = tc.dotnet, arguments = [tc.runner.path, "layout", request.path], inputs = depset([request, tc.runner] + ctx.files.paths, transitive = [tc.sdk, tc.runner_support]), outputs = [output], mnemonic = "MSBuildLayout", execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1"})
    return [DefaultInfo(files = depset([output])), MSBuildLayoutInfo(directory = output)]

msbuild_layout = rule(implementation = _layout, attrs = {"paths": attr.label_keyed_string_dict(allow_files = True)}, toolchains = [_TOOLCHAIN])

def _runtime(ctx):
    path = ctx.attr.entry_point
    if path.startswith("/") or "\\" in path or any([p in ["", ".", ".."] for p in path.split("/")]):
        fail("Runtime entry_point must be a safe relative path")
    directory = ctx.attr.layout[MSBuildLayoutInfo].directory
    return [DefaultInfo(files = depset([directory])), MSBuildRuntimeInfo(directory = directory, entry_point = path)]

msbuild_runtime = rule(implementation = _runtime, attrs = {
    "layout": attr.label(mandatory = True, providers = [MSBuildLayoutInfo]),
    "entry_point": attr.string(mandatory = True),
})

def _reference_pack(ctx):
    files = ctx.files.srcs + [dep[MSBuildAssemblyInfo].reference for dep in ctx.attr.assemblies]
    if not files or any([f.extension != "dll" or f.is_directory for f in files]):
        fail("A reference pack requires explicit assembly DLLs")
    references = depset(files, transitive = [dep[MSBuildAssemblyInfo].references for dep in ctx.attr.assemblies])
    return [DefaultInfo(files = references), MSBuildReferencePackInfo(references = references)]

msbuild_reference_pack = rule(implementation = _reference_pack, attrs = {
    "srcs": attr.label_list(allow_files = [".dll"]),
    "assemblies": attr.label_list(providers = [MSBuildAssemblyInfo]),
})

def _native_tool(ctx):
    directory = ctx.attr.layout[MSBuildLayoutInfo].directory
    return [DefaultInfo(files = depset([directory])), MSBuildToolInfo(native = True, layout_prefix = "", properties = {}, project = "native-tools/" + ctx.label.name, entry_point = ctx.attr.entry_point, directories = depset([directory]), packages = depset(), data = [], files = depset([directory]))]

msbuild_native_tool = rule(implementation = _native_tool, attrs = {
    "layout": attr.label(mandatory = True, providers = [MSBuildLayoutInfo]),
    "entry_point": attr.string(mandatory = True),
})
