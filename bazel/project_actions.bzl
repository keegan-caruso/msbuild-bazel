"""Per-project compilation with stable API dependencies and runtime composition."""

load(":input_paths.bzl", "input_path")
load(":native_cache.bzl", "NativeBundle")
load(":nuget_package.bzl", "NugetPackageSetInfo", "package_files", "package_rows")
load(":preparation.bzl", "DiscoveryPlanInfo")

ProjectBundleInfo = provider(doc = "Project API and runtime outputs with their transitive closures.", fields = ["api", "apis", "bundle", "runtimes", "dependency_runtimes"])

def _project(ctx):
    discovery = ctx.attr.discovery[DiscoveryPlanInfo].projects.get(ctx.attr.project, ctx.attr.discovery[DiscoveryPlanInfo].directory)
    plan = ctx.actions.declare_directory(ctx.label.name + ".plan")
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    api = ctx.actions.declare_directory(ctx.label.name + ".api")
    runtime = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    bind = ctx.actions.declare_file(ctx.label.name + ".bind.json")
    ctx.actions.write(bind, json.encode({
        "discovery": discovery.path,
        "output": plan.path,
        "project": ctx.attr.project,
        "dependencies": ctx.attr.project_dependencies,
        "sources": [{"source": f.path, "destination": input_path(f)} for f in ctx.files.sources],
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.preparation.path, "owned-bind-sources", "--request", bind.path],
        inputs = depset(ctx.attr.discovery[DiscoveryPlanInfo].validation + ctx.files.sources + ctx.files.runner_support + [discovery, bind, ctx.file.preparation], transitive = [ctx.attr.sdk[DefaultInfo].files]),
        outputs = [plan],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildBindProject",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    dependencies = depset(transitive = [dep[ProjectBundleInfo].apis for dep in ctx.attr.dependencies])
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({
        "entry": ctx.attr.project,
        "output": output.path,
        "diagnostics": diagnostics.path,
        "manifest": plan.path + "/manifest.json",
        "restore": plan.path + "/restore.json",
        "preparedPlan": plan.path,
        "sources": [{"source": f.path, "destination": input_path(f)} for f in ctx.files.sources + ctx.files.structural],
        "packageDirectories": package_rows(ctx.attr.package_set),
        "seeds": [],
        "projectAction": True,
        "apiOutput": api.path,
        "runtimeOutput": runtime.path,
        "prebuilt": [f.path for f in dependencies.to_list()],
    }))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--portable-request", request.path],
        inputs = depset(ctx.files.sources + ctx.files.structural + package_files(ctx.attr.package_set) + ctx.files.runner_support + [plan, request, ctx.file.runner], transitive = [dependencies, ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output, api, runtime, diagnostics],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildCompileProject",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    dependency_runtimes = depset(transitive = [dep[ProjectBundleInfo].runtimes for dep in ctx.attr.dependencies])
    return [DefaultInfo(files = depset([output])), ProjectBundleInfo(api = api, apis = depset([api], transitive = [dependencies]), bundle = output, runtimes = depset([runtime], transitive = [dependency_runtimes]), dependency_runtimes = dependency_runtimes)]

msbuild_compile_project = rule(implementation = _project, attrs = {
    "package_set": attr.label(providers = [NugetPackageSetInfo]),
    "project": attr.string(mandatory = True),
    "project_dependencies": attr.string_list(),
    "discovery": attr.label(providers = [DiscoveryPlanInfo]),
    "sources": attr.label_list(allow_files = True),
    "structural": attr.label_list(allow_files = True),
    "dependencies": attr.label_list(providers = [ProjectBundleInfo]),
    "preparation": attr.label(allow_single_file = True, mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})

def _runtime(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".bundle")
    metadata = ctx.actions.declare_directory(ctx.label.name + ".metadata")
    entry = ctx.attr.entry[ProjectBundleInfo]
    bundles = entry.dependency_runtimes
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    ctx.actions.write(request, json.encode({"entry": ctx.attr.project, "output": output.path, "bundles": [], "entryBundle": entry.bundle.path, "runtimeBundles": [f.path for f in bundles.to_list()], "metadataOutput": metadata.path}))
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--compose-projects", request.path],
        inputs = depset([ctx.file.runner, request, entry.bundle] + ctx.files.runner_support, transitive = [bundles, ctx.attr.sdk[DefaultInfo].files]),
        outputs = [output, metadata],
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        mnemonic = "MsbuildComposeRuntime",
        execution_requirements = {"block-network": "1", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset([output, metadata])), NativeBundle(bundle = output, metadata = metadata)]

msbuild_compose_runtime = rule(implementation = _runtime, attrs = {
    "entry": attr.label(providers = [ProjectBundleInfo], mandatory = True),
    "project": attr.string(mandatory = True),
    "runner": attr.label(allow_single_file = True, mandatory = True),
    "runner_support": attr.label_list(allow_files = True),
    "sdk": attr.label(mandatory = True),
    "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "exec", mandatory = True),
})
