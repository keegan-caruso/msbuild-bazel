"""Opt-in MSBuild traversal graph actions with explicit project contracts."""

load("//msbuild/private:paths.bzl", _quote = "quote", _runfile = "runfile")

MSBuildGraphInfo = provider("A declared MSBuild graph workspace and its execution SDK.", fields = {"directory": "Graph output workspace", "dotnet": "Execution host", "sdk": "Declared SDK files", "projects": "Configured project runtime outputs"})

def _runner(ctx):
    tc = ctx.toolchains["//msbuild:toolchain_type"]
    output = ctx.actions.declare_directory(ctx.label.name + ".runner")
    ctx.actions.run_shell(
        inputs = depset(ctx.files._sources, transitive = [tc.sdk]),
        tools = [tc.dotnet],
        outputs = [output],
        arguments = [tc.dotnet.path, ctx.file._project.path, output.path],
        command = """set -eu
dotnet="$PWD/$1"; project="$PWD/$2"; output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1
"$dotnet" build "$project" -c Release -o "$output" --nologo \
  -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \
  -p:RestoreSources="$scratch/empty" -p:NuGetAudit=false
""",
        mnemonic = "MSBuildGraphBootstrap",
    )
    return [DefaultInfo(files = depset([output]))]

msbuild_graph_runner = rule(
    implementation = _runner,
    attrs = {
        "_sources": attr.label(default = "//tools/GraphBuild:sources"),
        "_project": attr.label(default = "//tools/GraphBuild:GraphBuild.csproj", allow_single_file = True),
    },
    toolchains = ["//msbuild:toolchain_type"],
)

def _graph(ctx):
    tc = ctx.toolchains["//msbuild:toolchain_type"]
    output = ctx.actions.declare_directory(ctx.label.name + ".graph")
    runner = ctx.attr.runner[DefaultInfo].files.to_list()
    if len(runner) != 1:
        fail("runner must provide one graph runner payload")
    prefix = ctx.attr.source_root + "/" if ctx.attr.source_root else ""
    args = ctx.actions.args()
    args.add_all([tc.dotnet.path, runner[0].path, output.path, ctx.file.contract.path, ctx.attr.target])
    for file in ctx.files.srcs:
        if not file.short_path.startswith(prefix):
            fail("Graph source is outside source_root: " + file.short_path)
        relative = file.short_path[len(prefix):]
        if relative.startswith("/") or any([part in ["", ".", ".."] for part in relative.split("/")]):
            fail("Graph source requires a safe workspace-relative destination: " + relative)
        args.add_all([file.path, relative])
    for file in ctx.files.packages:
        args.add_all([file.path, ".package-source/" + file.basename])
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + ctx.files.packages + [ctx.file.contract, runner[0]], transitive = [tc.sdk]),
        tools = [tc.dotnet],
        outputs = [output],
        arguments = [args],
        env = {key: value for key, value in ctx.configuration.default_shell_env.items() if key.startswith("RULES_MSBUILD_PROJECT_CACHE_")},
        command = """set -eu
dotnet="$PWD/$1"; runner="$PWD/$2"; output="$PWD/$3"; contract="$PWD/$4"; target="$5"
shift 5
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
workspace="$output/workspace"
mkdir -p "$workspace"
while test "$#" -gt 0; do
    source="$PWD/$1"; relative="$2"; shift 2
    test ! -e "$workspace/$relative"
    mkdir -p "$workspace/$(dirname "$relative")"
    cp -pL "$source" "$workspace/$relative"
done
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1
export MSBUILDDISABLENODEREUSE=1
"$dotnet" exec "$runner/GraphBuild.dll" action "$workspace" "$contract" "$output/report.json" "$scratch/cache" "$target"
""",
        mnemonic = "MSBuildGraph",
    )
    return [DefaultInfo(files = depset([output])), MSBuildGraphInfo(directory = output, dotnet = tc.dotnet, sdk = tc.sdk, projects = ctx.attr.project_outputs)]

msbuild_graph = rule(
    implementation = _graph,
    attrs = {
        "contract": attr.label(allow_single_file = [".json"], mandatory = True),
        "runner": attr.label(mandatory = True, cfg = "exec"),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "packages": attr.label_list(allow_files = [".nupkg"]),
        "source_root": attr.string(),
        "project_outputs": attr.string_list_dict(),
        "target": attr.string(default = "Build", values = ["Build", "Publish"]),
    },
    toolchains = ["//msbuild:toolchain_type"],
)

def _runtime(ctx):
    graph = ctx.attr.graph[MSBuildGraphInfo]
    assembly = ctx.attr.assembly
    if ctx.attr.project:
        if assembly:
            fail("Use project or assembly, not both")
        candidates = [value for key, value in graph.projects.items() if key.split("|")[0] == ctx.attr.project and (not ctx.attr.framework or key.split("|")[1] == ctx.attr.framework)]
        if len(candidates) != 1:
            fail("Select one generated project/framework with project and framework: " + ctx.attr.project)
        directory, assembly, kind = candidates[0]
        if kind.lower() not in ["exe", "winexe"]:
            fail("Run and executable tests require an executable project: " + ctx.attr.project)
    else:
        if not assembly or "/" not in assembly:
            fail("Specify a generated project or a workspace-relative assembly path")
        directory, assembly = assembly.rsplit("/", 1)
    for path in [directory, assembly]:
        if path.startswith("/") or any([part in ["", ".", ".."] for part in path.split("/")]) or "\\" in path:
            fail("Runtime outputs must be safe workspace-relative paths")
    output = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    ctx.actions.run_shell(
        inputs = [graph.directory],
        outputs = [output],
        arguments = [graph.directory.path + "/workspace/" + directory, output.path, assembly],
        command = 'set -eu; test -f "$1/$3"; mkdir -p "$2"; cp -pRL "$1/." "$2/"',
        mnemonic = "MSBuildGraphRuntime",
    )
    launcher = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(
        launcher,
        """#!/usr/bin/env bash
set -euo pipefail
runfiles="${RUNFILES_DIR:-$0.runfiles}"
dotnet="$runfiles/"%s
assembly="$runfiles/"%s
export DOTNET_ROOT="$(dirname "$dotnet")"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
if [[ -n "${TEST_TMPDIR:-}" ]]; then
    export DOTNET_CLI_HOME="$TEST_TMPDIR"
    cd "$TEST_TMPDIR"
fi
exec "$dotnet" exec "$assembly" "$@"
""" % (_quote(_runfile(ctx, graph.dotnet)), _quote(_runfile(ctx, output) + "/" + assembly)),
        is_executable = True,
    )
    return [DefaultInfo(executable = launcher, runfiles = ctx.runfiles(files = [output, graph.dotnet], transitive_files = graph.sdk))]

_RUNTIME_ATTRS = {
    "graph": attr.label(providers = [MSBuildGraphInfo], mandatory = True),
    "project": attr.string(),
    "framework": attr.string(),
    "assembly": attr.string(),
}

msbuild_graph_binary = rule(
    implementation = _runtime,
    attrs = _RUNTIME_ATTRS,
    executable = True,
)

msbuild_graph_test = rule(
    implementation = _runtime,
    attrs = _RUNTIME_ATTRS,
    test = True,
)
