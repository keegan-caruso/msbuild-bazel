"""Explicit project graph, generic MSBuild items, and executable tests."""

MSBuildPackageInfo = provider("Locked package extraction and dependency closure.", fields = ["id", "version", "directory", "rows", "files"])

MSBuildAssemblyInfo = provider("Reference assembly and separate runtime dependency closure.", fields = ["project", "framework", "reference", "references", "runtime", "runtimes", "packages", "package_files", "compile_packages", "runtime_data"])
MSBuildItemsInfo = provider("Explicit MSBuild items with declared files and metadata.", fields = ["items", "files"])
_TOOLCHAIN = Label("//msbuild:toolchain_type")

def _logical(file):
    path = file.short_path
    if path.startswith("../"):
        # Keep repository identities in the logical namespace.
        return "external/" + path[3:]
    return path

def _file(file):
    return {"source": file.path, "path": _logical(file)}

def _items(ctx):
    rows = [{"type": ctx.attr.item_type, "file": _file(file), "metadata": ctx.attr.metadata} for file in ctx.files.srcs]
    return [DefaultInfo(files = depset(ctx.files.srcs)), MSBuildItemsInfo(items = rows, files = depset(ctx.files.srcs))]

msbuild_items = rule(
    implementation = _items,
    attrs = {
        "item_type": attr.string(mandatory = True),
        "srcs": attr.label_list(allow_files = True),
        "metadata": attr.string_dict(),
    },
)

def _quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"

def _runfile(ctx, file):
    if file.short_path.startswith("../"):
        return file.short_path[3:]
    return ctx.workspace_name + "/" + file.short_path

def _project(ctx, executable = False, test = False):
    tc = ctx.toolchains[_TOOLCHAIN]
    name = ctx.attr.assembly_name or ctx.file.project.basename.removesuffix(".csproj")
    reference = ctx.actions.declare_file(ctx.label.name + ".reference/" + name + ".dll")
    runtime = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    diagnostics = ctx.actions.declare_directory(ctx.label.name + ".diagnostics")
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")
    items = []
    for group in ctx.attr.items:
        items.extend(group[MSBuildItemsInfo].items)
    direct = [dep[MSBuildAssemblyInfo] for dep in ctx.attr.deps if MSBuildAssemblyInfo in dep]
    compile_targets = [dep for dep in ctx.attr.deps if MSBuildPackageInfo in dep]
    compile_packages = depset([row["id"] for dep in compile_targets for row in dep[MSBuildPackageInfo].rows], transitive = [dep.compile_packages for dep in direct])
    package_targets = compile_targets + ctx.attr.build_deps + ctx.attr.analyzers
    package_rows = {}
    for dep in package_targets:
        for row in dep[MSBuildPackageInfo].rows:
            key = row["id"].lower()
            if key in package_rows and package_rows[key] != row:
                fail("Conflicting locked package: " + key)
            package_rows[key] = row
    for dep in direct:
        for row in dep.packages:
            key = row["id"].lower()
            if key in package_rows and package_rows[key] != row:
                fail("Conflicting inherited package: " + key)
            package_rows[key] = row
    package_files = depset(transitive = [dep[MSBuildPackageInfo].files for dep in package_targets] + [dep.package_files for dep in direct])
    for dep in direct:
        if dep.framework != ctx.attr.target_framework:
            fail("This initial slice requires matching target frameworks: " + dep.project)
    references = depset([dep.reference for dep in direct], transitive = [dep.references for dep in direct])
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
    ctx.actions.write(request, json.encode({
        "project": _file(ctx.file.project),
        "sources": [_file(file) for file in ctx.files.srcs],
        "imports": [_file(file) for file in ctx.files.msbuild_imports],
        "items": items,
        "dependencies": [dep.project for dep in direct],
        "references": [file.path for file in references.to_list()],
        "framework": ctx.attr.target_framework,
        "frameworkReferences": ctx.attr.framework_refs,
        "assembly": name,
        "executable": executable,
        "configuration": "Debug" if ctx.var["COMPILATION_MODE"] == "dbg" else "Release",
        "properties": ctx.attr.msbuild_properties,
        "packages": package_rows.values(),
        "compilePackages": compile_packages.to_list(),
        "declaredPackages": [dep[MSBuildPackageInfo].id for dep in package_targets],
        "buildPackages": [row["id"] for dep in ctx.attr.build_deps for row in dep[MSBuildPackageInfo].rows],
        "analyzerPackages": [row["id"] for dep in ctx.attr.analyzers for row in dep[MSBuildPackageInfo].rows],
        "defines": ctx.attr.defines,
        "nullable": ctx.attr.nullable,
        "languageVersion": ctx.attr.lang_version,
        "allowUnsafe": ctx.attr.allow_unsafe,
        "runtime": runtime.path,
        "reference": reference.path,
        "diagnostics": diagnostics.path,
        "sdkVersion": tc.sdk_version,
        "runtimeManifest": tc.runtime_manifest.path,
    }))
    arguments = [tc.runner.path, "build", request.path]
    requirements = {"no-sandbox": "1", "no-remote-exec": "1"}
    if ctx.attr.linux_worker:
        params = ctx.actions.args()
        params.add(request.path)
        params.use_param_file("@%s", use_always = True)
        params.set_param_file_format("multiline")
        arguments = [tc.runner.path, "--bazel-worker", params]
        requirements.update({"supports-workers": "1", "requires-worker-protocol": "json"})
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = arguments,
        tools = depset([tc.runner], transitive = [tc.sdk, tc.runner_support]) if ctx.attr.linux_worker else [],
        inputs = depset(
            [ctx.file.project, request, tc.runner, tc.runtime_manifest] + ctx.files.srcs + ctx.files.msbuild_imports,
            transitive = [tc.sdk, tc.runner_support, references, package_files] + [group[MSBuildItemsInfo].files for group in ctx.attr.items],
        ),
        outputs = [reference, runtime, diagnostics],
        mnemonic = "MSBuildAssembly",
        env = {"LANG": "en_US.UTF-8"},
        # The runner stages only declared files and starts a deny-by-default
        # child sandbox. macOS does not permit nested sandbox-exec.
        execution_requirements = requirements,
    )
    info = MSBuildAssemblyInfo(
        project = _logical(ctx.file.project),
        framework = ctx.attr.target_framework,
        reference = reference,
        references = references,
        runtime = runtime,
        runtimes = runtimes,
        packages = package_rows.values(),
        package_files = package_files,
        compile_packages = compile_packages,
        runtime_data = runtime_data,
    )
    if not executable:
        return [DefaultInfo(files = depset([runtime])), info, OutputGroupInfo(reference = depset([reference]), diagnostics = depset([diagnostics]))]
    launch_request = ctx.actions.declare_file(ctx.label.name + ".launch.json")
    ctx.actions.write(launch_request, json.encode({
        "entry": _runfile(ctx, runtime),
        "dependencies": [_runfile(ctx, file) for file in runtimes.to_list()],
        "assembly": name,
        "test": test,
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
        files = [tc.dotnet, tc.runner, runtime, launch_request] + [row.file for row in runtime_data.to_list()],
        transitive_files = depset(transitive = [tc.sdk, tc.runner_support, runtimes]),
    )
    return [DefaultInfo(executable = launcher, files = depset([runtime]), runfiles = runfiles), info, OutputGroupInfo(reference = depset([reference]), diagnostics = depset([diagnostics]))]

def _library(ctx):
    return _project(ctx)

def _binary(ctx):
    return _project(ctx, executable = True)

def _test(ctx):
    if ctx.attr.shard_count > 1:
        fail("Executable tests do not yet support sharding")
    return _project(ctx, executable = True, test = True)

_ATTRS = {
    "linux_worker": attr.bool(default = False),
    "project": attr.label(allow_single_file = [".csproj"], mandatory = True),
    "target_framework": attr.string(mandatory = True),
    "assembly_name": attr.string(),
    "srcs": attr.label_list(allow_files = True),
    "items": attr.label_list(providers = [MSBuildItemsInfo]),
    "deps": attr.label_list(providers = [[MSBuildAssemblyInfo], [MSBuildPackageInfo]]),
    "build_deps": attr.label_list(providers = [MSBuildPackageInfo]),
    "analyzers": attr.label_list(providers = [MSBuildPackageInfo]),
    "framework_refs": attr.string_list(),
    "msbuild_imports": attr.label_list(allow_files = True),
    "msbuild_properties": attr.string_dict(),
    "defines": attr.string_list(),
    "nullable": attr.string(default = "enable", values = ["enable", "disable", "warnings", "annotations"]),
    "lang_version": attr.string(default = "default"),
    "allow_unsafe": attr.bool(),
    "data": attr.label_list(allow_files = True),
    "data_paths": attr.label_keyed_string_dict(allow_files = True),
}

msbuild_library = rule(implementation = _library, attrs = _ATTRS, toolchains = [_TOOLCHAIN])
msbuild_binary = rule(implementation = _binary, attrs = _ATTRS, toolchains = [_TOOLCHAIN], executable = True)
msbuild_test = rule(implementation = _test, attrs = _ATTRS, toolchains = [_TOOLCHAIN], test = True)

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
        inputs = depset([ctx.file.archive, request, tc.runner], transitive = [tc.sdk, tc.runner_support]),
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
