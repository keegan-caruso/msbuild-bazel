"""Cache synchronization only when the complete source workspace is declared."""

load(":paths.bzl", "quote", "runfile")

def prepare_sync(ctx, tc, payload, manifest, bound_files):
    """Create cacheable preparation and its runnable publisher.

    Args:
        ctx: Synchronization rule context.
        tc: Selected SDK toolchain.
        payload: Built ProjectSync directory.
        manifest: Producer and package bindings.
        bound_files: Producer, package and task-tool artifacts.

    Returns:
        DefaultInfo containing prepared declarations and their publisher.
    """
    if ctx.label.workspace_name:
        fail("Cached sync publishes in the main workspace; declare it in that workspace's root package")
    if not ctx.files.srcs:
        fail("Cached sync requires a nonempty srcs workspace snapshot")
    sources = []
    for file in ctx.files.srcs:
        if not file.is_source or file.owner.workspace_name != ctx.label.workspace_name or file.owner.package:
            fail("sync srcs require authored files from the root Bazel package; use inputs for producers")
        path = (file.owner.package + "/" if file.owner.package else "") + file.owner.name
        if path in ["graph.generated.json", "graph.generated.bzl"]:
            fail("Exclude graph.generated.json and graph.generated.bzl from sync srcs")
        sources.append({"path": path, "file": file.path})
    stage = ctx.actions.declare_file(ctx.label.name + ".sync-stage.json")
    ctx.actions.write(stage, json.encode({
        "sources": sources,
        "runfiles": [{"path": path, "file": file.path} for path, file in {runfile(ctx, file): file for file in bound_files}.items()],
    }))
    prepared = ctx.actions.declare_directory(ctx.label.name + ".sync-prepared")
    flags = ["--configuration", ctx.attr.configuration]
    if ctx.attr.framework:
        flags.extend(["--framework", ctx.attr.framework])
    if ctx.attr.package_build:
        flags.append("--package-build")
    if ctx.attr.resolve_references:
        flags.append("--resolve-references")
    for path in ctx.attr.package_inputs:
        flags.extend(["--package-input", path])
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + bound_files + [payload, manifest, stage] + ([ctx.file.mappings] if ctx.file.mappings else []), transitive = [tc.sdk]),
        tools = [tc.dotnet],
        outputs = [prepared],
        arguments = [tc.dotnet.path, payload.path, stage.path, prepared.path, manifest.path, tc.sdk_version, ctx.file.mappings.path if ctx.file.mappings else ""] + ctx.attr.projects,
        command = """set -eu
base="$PWD"
dotnet="$base/$1"; runner="$base/$2/ProjectSync.dll"; stage="$base/$3"; output="$base/$4"
manifest="$base/$5"; version=$6; mappings=$7
shift 7
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch/home"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false DOTNET_MULTILEVEL_LOOKUP=0
"$dotnet" "$runner" stage "$stage" "$scratch"
if [ -n "$mappings" ]; then set -- "$@" --mappings "$base/$mappings"; fi
"$dotnet" "$runner" "$scratch/workspace" "$DOTNET_ROOT/sdk/$version" "$@" %s --inputs "$manifest" --runfiles "$scratch/runfiles"
mkdir -p "$output"
cp "$scratch/workspace/graph.generated.json" "$scratch/workspace/graph.generated.bzl" "$output/"
""" % " ".join([quote(flag) for flag in flags]),
        mnemonic = "MSBuildSyncPrepare",
        progress_message = "Qualifying declared MSBuild graph %s" % ctx.label,
    )
    launcher = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.write(launcher, """#!/usr/bin/env bash
set -euo pipefail
runfiles="${RUNFILES_DIR:-$0.runfiles}"
export DOTNET_ROOT="$runfiles/"%s
export DOTNET_NOLOGO=1 DOTNET_CLI_TELEMETRY_OPTOUT=1
exec "$runfiles/"%s "$runfiles/"%s publish "$runfiles/"%s "${BUILD_WORKSPACE_DIRECTORY:?Run with bazel run}" "$@"
""" % (
        quote(runfile(ctx, tc.dotnet).rsplit("/", 1)[0]),
        quote(runfile(ctx, tc.dotnet)),
        quote(runfile(ctx, payload) + "/ProjectSync.dll"),
        quote(runfile(ctx, prepared)),
    ), is_executable = True)
    return DefaultInfo(files = depset([prepared]), executable = launcher, runfiles = ctx.runfiles(files = [payload, prepared, tc.dotnet], transitive_files = tc.sdk))
