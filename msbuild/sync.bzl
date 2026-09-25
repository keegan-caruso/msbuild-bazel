"""Local project synchronization, invoked explicitly with bazel run."""

load("//msbuild/private:paths.bzl", _TOOLCHAIN = "TOOLCHAIN", _quote = "quote", _runfile = "runfile")

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
exec "$runfiles/"%s "$runfiles/"%s "$BUILD_WORKSPACE_DIRECTORY" "$DOTNET_ROOT/sdk/"%s %s %s "$@"
""" % (
        _quote(_runfile(ctx, tc.dotnet).rsplit("/", 1)[0]),
        _quote(_runfile(ctx, tc.dotnet)),
        _quote(_runfile(ctx, payload) + "/ProjectSync.dll"),
        _quote(tc.sdk_version),
        " ".join([_quote(project) for project in ctx.attr.projects]),
        '--mappings "$runfiles/"' + _quote(_runfile(ctx, ctx.file.mappings)) if ctx.file.mappings else "",
    ), is_executable = True)
    return [DefaultInfo(
        executable = launcher,
        runfiles = ctx.runfiles(files = [payload, tc.dotnet] + ([ctx.file.mappings] if ctx.file.mappings else []), transitive_files = tc.sdk),
    )]

_sync = rule(
    implementation = _sync_impl,
    executable = True,
    toolchains = [_TOOLCHAIN],
    attrs = {
        "projects": attr.string_list(mandatory = True),
        "mappings": attr.label(allow_single_file = [".json"]),
        "_sources": attr.label(default = Label("//tools/ProjectSync:sources")),
        "_project": attr.label(default = Label("//tools/ProjectSync:ProjectSync.csproj"), allow_single_file = True),
    },
)

def msbuild_sync(name, projects, mappings = None, **kwargs):
    """Declare a tool that evaluates local projects and writes projects.generated.bzl.

    Args:
        name: Runnable target name, conventionally sync.
        projects: Workspace-relative entry csproj paths, not labels. References are discovered at run time.
        mappings: Optional JSON file with explicit package and test bindings.
        **kwargs: Common Bazel attributes such as visibility and tags.
    """
    if not projects:
        fail("msbuild_sync requires at least one entry project")
    for project in projects:
        if project.startswith("/") or "\\" in project or any([part in ["", ".", ".."] for part in project.split("/")]) or not project.endswith(".csproj"):
            fail("Expected a workspace-relative csproj path: " + project)
    _sync(name = name, projects = projects, mappings = mappings, **kwargs)
