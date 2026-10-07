"""Local project synchronization, invoked explicitly with bazel run."""

load("//msbuild/private:paths.bzl", _TOOLCHAIN = "TOOLCHAIN", _quote = "quote", _runfile = "runfile")
load("//msbuild/private:providers.bzl", "MSBuildBindingInfo", "MSBuildPackageLockInfo")

def _sync_impl(ctx):
    if ctx.label.package:
        fail("msbuild_sync currently belongs in the workspace root BUILD file")
    tc = ctx.toolchains[_TOOLCHAIN]
    payload = ctx.actions.declare_directory(ctx.label.name + ".project-sync")
    ctx.actions.run_shell(
        inputs = depset(ctx.files._sources, transitive = [tc.sdk]),
        tools = [tc.dotnet],
        outputs = [payload],
        arguments = [tc.dotnet.path, ctx.file._project.path, payload.path],
        command = """set -eu
dotnet="$PWD/$1"; project="$PWD/$2"; output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false DOTNET_MULTILEVEL_LOOKUP=0
export NUGET_PACKAGES="$scratch/packages"
cd "$scratch"
"$dotnet" build "$project" -c Release -o "$output" --nologo \\
    -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \\
    -p:RestoreSources="$scratch/empty" -p:NuGetAudit=false -p:DebugType=None
""",
        mnemonic = "MSBuildSyncBootstrap",
    )
    bound = []
    input_files = []
    for target, path in ctx.attr.inputs.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("sync inputs require exactly one file per label")
        bound.append({"path": path, "label": str(target.label), "runfile": _runfile(ctx, files[0])})
        input_files.extend(files)
    packages = []
    package_files = []
    locks = {str(target.label): target for target in ctx.attr.package_locks + ([ctx.attr.package_lock] if ctx.attr.package_lock else [])}
    package_files = depset(transitive = [target[MSBuildPackageLockInfo].files for target in locks.values()]).to_list()
    by_path = {file.path: file for file in package_files}
    identities = {}
    package_locks = []
    for label, target in locks.items():
        members = []
        for row in target[MSBuildPackageLockInfo].rows:
            identity = row["id"].lower() + "/" + row["version"].lower()
            if identity in identities and identities[identity] != row:
                fail("Conflicting sync package source: " + identity)
            identities[identity] = row
            members.append(identity)
        package_locks.append({"label": label, "packages": members})
    packages = [{"id": row["id"], "version": row["version"], "runfile": _runfile(ctx, by_path[row["directory"]])} for row in identities.values()]
    evaluation_bindings = []
    binding_files = []
    for target in ctx.attr.bindings:
        binding = target[MSBuildBindingInfo]
        tool = binding.tool
        closure = binding.tool.directory
        evaluation_bindings.append({"label": str(target.label), "property": binding.property_name, "runfiles": [_runfile(ctx, closure)], "entry": tool.entry_point, "closure": True})
        binding_files.append(closure)
    manifest = ctx.actions.declare_file(ctx.label.name + ".sync-inputs.json")
    ctx.actions.write(manifest, json.encode({"inputs": bound, "packages": packages, "packageLock": str(ctx.attr.package_lock.label) if ctx.attr.package_lock else None, "bindings": evaluation_bindings, "packageLocks": package_locks}))
    launcher = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.write(launcher, """#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${BUILD_WORKSPACE_DIRECTORY:-}" ]]; then
    echo 'Run this target with bazel run from the application workspace.' >&2
    exit 1
fi
runfiles="${RUNFILES_DIR:-$0.runfiles}"
export DOTNET_ROOT="$runfiles/"%s
export DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
exec "$runfiles/"%s "$runfiles/"%s "$BUILD_WORKSPACE_DIRECTORY" "$DOTNET_ROOT/sdk/"%s %s %s %s --inputs "$runfiles/"%s --runfiles "$runfiles" "$@"
""" % (
        _quote(_runfile(ctx, tc.dotnet).rsplit("/", 1)[0]),
        _quote(_runfile(ctx, tc.dotnet)),
        _quote(_runfile(ctx, payload) + "/ProjectSync.dll"),
        _quote(tc.sdk_version),
        " ".join([_quote(project) for project in ctx.attr.projects]),
        '--mappings "$runfiles/"' + _quote(_runfile(ctx, ctx.file.mappings)) if ctx.file.mappings else "",
        "--configuration " + _quote(ctx.attr.configuration) + (" --framework " + _quote(ctx.attr.framework) if ctx.attr.framework else "") + (" --package-build" if ctx.attr.package_build else "") + (" --resolve-references" if ctx.attr.resolve_references else "") + "".join([" --package-input " + _quote(path) for path in ctx.attr.package_inputs]),
        _quote(_runfile(ctx, manifest)),
    ), is_executable = True)
    return [DefaultInfo(
        executable = launcher,
        runfiles = ctx.runfiles(files = [payload, tc.dotnet, manifest] + input_files + package_files + binding_files + ([ctx.file.mappings] if ctx.file.mappings else []), transitive_files = tc.sdk),
    )]

_sync = rule(
    implementation = _sync_impl,
    executable = True,
    toolchains = [_TOOLCHAIN],
    attrs = {
        "projects": attr.string_list(mandatory = True),
        "configuration": attr.string(default = "Release"),
        "framework": attr.string(),
        "package_build": attr.bool(),
        "resolve_references": attr.bool(),
        "package_inputs": attr.string_list(),
        "bindings": attr.label_list(providers = [MSBuildBindingInfo], cfg = "exec"),
        "inputs": attr.label_keyed_string_dict(allow_files = True),
        "package_lock": attr.label(providers = [MSBuildPackageLockInfo]),
        "package_locks": attr.label_list(providers = [MSBuildPackageLockInfo]),
        "mappings": attr.label(allow_single_file = [".json"]),
        "_sources": attr.label(default = Label("//tools/ProjectSync:sources")),
        "_project": attr.label(default = Label("//tools/ProjectSync:ProjectSync.csproj"), allow_single_file = True),
    },
)

def msbuild_sync(name, projects, mappings = None, inputs = {}, package_lock = None, bindings = [], package_locks = [], configuration = "Release", framework = "", package_build = False, package_inputs = [], resolve_references = False, **kwargs):
    """Declare a tool that evaluates local projects and writes graph.generated.json and graph.generated.bzl.

    Args:
        name: Runnable target name, conventionally sync.
        projects: Workspace-relative entry .csproj, .ilproj or Traversal/NoTargets .proj paths, not labels. References are discovered at run time.
        configuration: Graph configuration, default Release.
        framework: Optional graph target framework; empty builds declared frameworks.
        package_build: Opt in to offline Restore and package build/content evaluation in a disposable copy.
        resolve_references: Run a private qualification Build and emit complete SDK-selected compiler/copy bindings at supported reference boundaries. Requires package_build.
        package_inputs: Additional workspace-relative files read by reviewed package tasks.
        mappings: Optional JSON file with reviewed input, output and dependency contracts.
        inputs: Single-file labels mapped to workspace-relative evaluation/build paths.
        bindings: Complete tool layouts bound to task properties during evaluation.
        package_lock: Optional default closed NuGet package set, including imported SDKs.
        package_locks: Additional package inventories available to evaluation.
        **kwargs: Common Bazel attributes such as visibility and tags.
    """
    if not projects:
        fail("msbuild_sync requires at least one entry project")
    if resolve_references and not package_build:
        fail("resolve_references requires package_build for private offline Restore and qualification Build")
    for project in projects:
        if project.startswith("/") or "\\" in project or any([part in ["", ".", ".."] for part in project.split("/")]) or not (project.endswith(".csproj") or project.endswith(".proj") or project.endswith(".ilproj")):
            fail("Expected a workspace-relative .csproj, .proj or .ilproj path: " + project)
    _sync(name = name, projects = projects, configuration = configuration, framework = framework, package_build = package_build, package_inputs = package_inputs, resolve_references = resolve_references, mappings = mappings, inputs = inputs, package_lock = package_lock, package_locks = package_locks, bindings = bindings, **kwargs)
