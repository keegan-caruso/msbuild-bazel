"""Register explicit project build actions and outputs."""

load(":paths.bzl", _NATIVE_TOOLCHAIN = "NATIVE_TOOLCHAIN", _TOOLCHAIN = "TOOLCHAIN", _file = "input_file", _logical = "logical", _mapped_imports = "mapped_imports", _runtime_package = "runtime_package")
load(":project_launch.bzl", "create_launcher")
load(":project_packages.bzl", "resolve_packages")
load(":providers.bzl", "MSBuildAssemblyInfo", "MSBuildBindingInfo", "MSBuildItemsInfo", "MSBuildLayoutInfo", "MSBuildPackageInfo", "MSBuildProjectInfo", "MSBuildProjectOutputInfo", "MSBuildReferencePackInfo", "MSBuildRestoreInfo", "MSBuildToolInfo")
load(":selection.bzl", "assembly_node", "restore_key", "select_closure")
load(":variants.bzl", "select_assembly")

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
    if ctx.attr.local_native_tools and not generate:
        fail("local_native_tools is currently supported only by msbuild_generate")
    if ctx.attr.local_native_tools and (ctx.attr.linux_worker or ctx.attr.allow_remote_execution):
        fail("local_native_tools requires a fresh local MSBuild action")
    if ctx.attr.native_toolchain and not generate:
        fail("native_toolchain is currently supported only by msbuild_generate")
    if ctx.attr.native_toolchain and not ctx.file.native_toolchain.is_directory:
        fail("native_toolchain requires a single tree artifact")
    if ctx.attr.native_toolchain and ctx.attr.local_native_tools:
        fail("Choose native_toolchain or local_native_tools")
    if ctx.attr.native_toolchain and ctx.attr.linux_worker:
        fail("native_toolchain requires a fresh MSBuild action")
    if ctx.attr.use_native_toolchain and not generate:
        fail("use_native_toolchain is currently supported only by msbuild_generate")
    if ctx.attr.use_native_toolchain and (ctx.attr.native_toolchain or ctx.attr.local_native_tools or ctx.attr.linux_worker):
        fail("use_native_toolchain requires a fresh action without native_toolchain or local_native_tools")
    native_tree = ctx.file.native_toolchain
    if ctx.attr.use_native_toolchain:
        selected_native = ctx.toolchains[_NATIVE_TOOLCHAIN]
        if selected_native == None:
            fail("No native toolchain matches this platform; register one or use native_toolchain")
        native_tree = selected_native.root
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
    public = [select_assembly(dep, ctx.attr.target_framework) for dep in ctx.attr.deps if MSBuildAssemblyInfo in dep or MSBuildProjectInfo in dep]
    bound_projects = {}
    for target, reference_name in ctx.attr.reference_projects.items():
        info = select_assembly(target, ctx.attr.target_framework)
        if reference_name != info.assembly or reference_name in bound_projects:
            fail("reference_projects requires a unique matching assembly name: " + reference_name)
        bound_projects[reference_name] = info.project
        public.append(info)
    implementation = [select_assembly(dep, ctx.attr.target_framework) for dep in ctx.attr.implementation_deps]
    direct = public + implementation
    if ctx.attr.output_mode != "reference" and any([dep.output_mode == "reference" for dep in direct]):
        fail("Reference-only dependencies require msbuild_assembly with an implementation")
    compile_targets = [dep for dep in ctx.attr.deps if MSBuildPackageInfo in dep] + ctx.attr.reference_packages
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
    packages = resolve_packages(ctx, public, direct, compile_targets, analyzer_packages)
    package_targets = packages.targets
    private_packages = packages.private_assets
    exported_compile_packages = packages.exported_compile
    package_rows = packages.rows
    compile_packages = packages.compile
    package_files = packages.files
    if len({dep.project: True for dep in direct}) != len(direct):
        fail("Select exactly one configured compile dependency per project")
    framework_references = depset(ctx.attr.framework_refs, transitive = [dep.framework_references for dep in direct])
    pack = ctx.attr.reference_pack[MSBuildReferencePackInfo] if ctx.attr.reference_pack else None
    pack_files = pack.references if pack else depset()
    references = depset([dep.reference for dep in direct], transitive = [dep.references for dep in direct])
    if not ctx.attr.transitive_compile_references and (executable or test):
        fail("Direct-only compilation references are supported only for libraries")
    dependency_nodes = depset([assembly_node(dep) for dep in direct], transitive = [dep.dependency_nodes for dep in direct])
    selected = select_closure(ctx, dependency_nodes, references, runtime_references, depset([dep.runtime for dep in direct], transitive = [dep.runtimes for dep in direct]), direct)
    exported_references = depset([dep.reference for dep in public], transitive = [dep.references for dep in public])
    exported_references = depset([selected.reference_choices.get(file.basename, file) for file in exported_references.to_list()]) if selected.reference_choices else exported_references
    references = selected.references
    runtime_references = selected.runtime_references
    compiler_references = references if ctx.attr.transitive_compile_references else depset([dep.reference for dep in direct])
    runtimes = selected.runtimes
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
    prepared_restore = ctx.attr.prepared_restore
    restore_source_files = ctx.files.restore_source_inputs
    restore_source_paths = {file.path: True for file in restore_source_files}
    if restore_source_files and not prepared_restore:
        fail("restore_source_inputs requires prepared_restore")
    compile_source_paths = {file.path: True for file in ctx.files.srcs + ctx.files.source_paths}
    if any([file.path not in compile_source_paths for file in restore_source_files]):
        fail("restore_source_inputs must be a subset of srcs and source_paths")
    if prepared_restore and (restore or restore_only or generate or ctx.attr.local_native_tools or selected.checks or bound_projects):
        fail("prepared_restore cannot combine with shared restore, generation, local native tools, assembly selections or reference_projects")
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
    prepared_file = ctx.actions.declare_file(ctx.label.name + ".prepared-restore.json") if prepared_restore else None
    request_data = {
        # Internal qualification gate; not part of the supported rule API.
        "experimentalWorkerProject": str(ctx.label) if ctx.attr.linux_worker and ctx.var.get("rules_msbuild_stable_path_prototype") == "1" else None,
        "localNativeTools": ctx.attr.local_native_tools,
        "nativeToolchain": native_tree.path if native_tree else None,
        "restoreKey": restore_key(ctx.attr.target_framework, ctx.attr.target_framework, _configuration(ctx), ctx.attr.msbuild_properties),
        "implementationReferences": [dep.project for dep in direct if dep.implementation_reference],
        "implementationDependencies": [dep.project for dep in implementation],
        "assemblySelections": selected.checks,
        "profileBuild": ctx.attr.profile_build,
        "restoreInput": restore.file.path if restore else prepared_file.path if prepared_file else None,
        "projectRestoreInput": prepared_restore,
        "restoreOnly": restore_only,
        "restoreProjectOutput": restore_project.path if restore_project else None,
        "restoreProjects": [file.path for file in restore_projects.to_list()],
        "project": _file(project),
        "referenceProjects": bound_projects,
        "sources": [_file(file) for file in ctx.files.srcs] + _mapped_imports(ctx, ctx.attr.source_paths),
        "directories": ctx.attr.directories,
        "generatedDirectories": ctx.attr.generated_directories,
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
    }
    ctx.actions.write(request, json.encode(request_data))
    if prepared_restore:
        prepared_diagnostics = ctx.actions.declare_directory(ctx.label.name + ".restore-diagnostics")
        prepared_request = ctx.actions.declare_file(ctx.label.name + ".prepared-request.json")
        restore_data = dict(request_data)
        restore_data.update({
            "assemblySelections": [],
            "diagnostics": prepared_diagnostics.path,
            "identityOutput": None,
            "profileBuild": False,
            "projectRestoreInput": False,
            "projectRestoreOnly": True,
            "reference": prepared_file.path,
            "references": [],
            "restoreInput": None,
            "restoreProjectOutput": None,
            "runtime": prepared_diagnostics.path,
            "runtimeReferences": [],
            "sources": [{"path": source["path"], "source": source["source"] if source["source"] in restore_source_paths else ""} for source in request_data["sources"]],
        })
        ctx.actions.write(prepared_request, json.encode(restore_data))
        prepared_arguments = [tc.runner.path, "build", prepared_request.path]
        prepared_requirements = {"no-sandbox": "1"}
        if not ctx.attr.allow_remote_execution:
            prepared_requirements["no-remote-exec"] = "1"
        if ctx.attr.linux_worker:
            prepared_params = ctx.actions.args()
            prepared_params.add(prepared_request.path)
            prepared_params.use_param_file("@%s", use_always = True)
            prepared_params.set_param_file_format("multiline")
            prepared_arguments = [tc.runner.path, "--bazel-worker", "--tool-inputs=" + tc.worker_tools.path, prepared_params]
            prepared_requirements.update({"supports-workers": "1", "requires-worker-protocol": "json"})
        ctx.actions.run(
            executable = tc.dotnet,
            arguments = prepared_arguments,
            tools = depset([tc.runner, tc.worker_tools], transitive = [tc.sdk, tc.runner_support]) if ctx.attr.linux_worker else [],
            inputs = depset(
                [project, prepared_request, tc.runner] + restore_source_files + ctx.files.msbuild_imports + ctx.files.import_paths + ctx.files.adapter_imports,
                transitive = [tc.sdk, tc.runner_support, pack_files, package_files, restore_projects, depset([p.assembly.reference if p.artifact == "reference" else p.assembly.runtime for p in project_outputs]), depset([dep.runtime for dep in analyzer_projects] + [row.directory for dep in analyzer_projects for row in dep.runtime_packages.to_list()], transitive = [dep.runtimes for dep in analyzer_projects]), depset([target[MSBuildLayoutInfo].directory for target in ctx.attr.layout_bindings])] + [group[MSBuildItemsInfo].files for group in ctx.attr.items] + [tool.files for tool in build_tools],
            ),
            outputs = [prepared_file, prepared_diagnostics],
            mnemonic = "MSBuildRestore",
            env = {"LANG": "en_US.UTF-8"},
            execution_requirements = prepared_requirements,
        )
    arguments = [tc.runner.path, "build", request.path]
    requirements = {"no-sandbox": "1"}
    if ctx.attr.local_native_tools:
        # The host C toolchain is outside Bazel's declared inputs. Keep this
        # local qualification path out of both local and remote action caches.
        requirements.update({"no-cache": "1", "no-remote": "1"})
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
            [project, request, tc.runner] + selected.files + ctx.files.srcs + ctx.files.source_paths + ctx.files.msbuild_imports + ctx.files.import_paths + ctx.files.adapter_imports + ([restore.file] if restore else []) + ([prepared_file] if prepared_file else []) + ([native_tree] if native_tree else []),
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
        dependency_nodes = dependency_nodes,
        selections = selected.selections,
        project = _logical(project),
        framework = ctx.attr.target_framework,
        reference_framework = ctx.attr.target_framework,
        restore_key = restore_key(ctx.attr.target_framework, ctx.attr.target_framework, _configuration(ctx), ctx.attr.msbuild_properties),
        configuration = _configuration(ctx),
        properties = ctx.attr.msbuild_properties,
        assembly = name,
        output_mode = ctx.attr.output_mode,
        implementation_reference = ctx.attr.output_mode == "implementation",
        identity = identity,
        reference = reference,
        references = exported_references,
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
    return create_launcher(ctx, tc, name, runtime, runtimes, runtime_packages, runtime_data, test) + [info, OutputGroupInfo(reference = depset([reference]), diagnostics = depset([diagnostics]), target_results = depset([target_output] if target_output else []))]
