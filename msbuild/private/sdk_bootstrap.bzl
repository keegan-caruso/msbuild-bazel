"""SDK-only bootstrap actions; deliberately independent of MSBuild toolchains."""

load(":providers.bzl", "MSBuildRuntimeInfo")

_RUNNER_FILES = [
    "ArtifactTools.dll",
    "ArtifactTools.deps.json",
    "ArtifactTools.runtimeconfig.json",
    "NuGet.Versioning.dll",
]

def bootstrap_project(ctx, dotnet, project, inputs, outputs, mnemonic, private_home = True, path_map = False):
    """Build a managed tool against an empty restore source.

    Args:
        ctx: Calling rule context.
        dotnet: SDK executable.
        project: Tool project file.
        inputs: Project sources and SDK files.
        outputs: One tree artifact or individual files in the same directory.
        mnemonic: Bazel action mnemonic.
        private_home: Set HOME to the action's scratch directory.
        path_map: Preserve portable debug symbols with mapped source paths.
    """
    home = 'export HOME="$native_scratch"' if private_home else ""
    if path_map:
        setup = 'repository="$(native_path "$(dirname "$(dirname "$(dirname "$project")")")")"'
        debug = '-p:PathMap="$repository=/_/rules_msbuild%2C$native_scratch=/_/bootstrap"'
    else:
        setup = """export DOTNET_GENERATE_ASPNET_CERTIFICATE=false
export DOTNET_MULTILEVEL_LOOKUP=0 NUGET_PACKAGES="$native_scratch/packages"
cd "$scratch"
"""
        debug = "-p:DebugType=None"
    ctx.actions.run_shell(
        inputs = inputs,
        tools = [dotnet],
        outputs = outputs,
        arguments = [dotnet.path, project.path, outputs[0].path if outputs[0].is_directory else outputs[0].dirname],
        command = """set -eu
dotnet="$PWD/$1"
project="$PWD/$2"
output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
native_path() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) cygpath -am "$1" ;;
        *) printf '%%s\\n' "$1" ;;
    esac
}
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) export MSYS2_ARG_CONV_EXCL='*' ;; esac
native_scratch="$(native_path "$scratch")"
export DOTNET_ROOT="$(native_path "$(dirname "$dotnet")")" DOTNET_CLI_HOME="$native_scratch"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export DOTNET_CLI_USE_MSBUILD_SERVER=false MSBUILDUSESERVER=0
%s
%s
"$dotnet" build "$(native_path "$project")" -c Release -o "$(native_path "$output")" --nologo \\
    -p:BaseIntermediateOutputPath="$native_scratch/obj/" -p:UseSharedCompilation=false \\
    -p:RestoreSources="$native_scratch/empty" -p:NuGetAudit=false %s
""" % (home, setup, debug),
        mnemonic = mnemonic,
    )

def _runner(ctx):
    outputs = [ctx.actions.declare_file(ctx.label.name + "/" + name) for name in _RUNNER_FILES]
    bootstrap_project(ctx, ctx.executable.dotnet, ctx.file.project, depset(ctx.files.sources + ctx.files.sdk), outputs, "MSBuildRunnerBootstrap")
    return [DefaultInfo(files = depset(outputs)), OutputGroupInfo(runner = depset([outputs[0]]))]

sdk_runner = rule(
    implementation = _runner,
    attrs = {
        "dotnet": attr.label(executable = True, cfg = "exec", allow_single_file = True, mandatory = True),
        "sdk": attr.label(mandatory = True),
        "project": attr.label(allow_single_file = True, mandatory = True),
        "sources": attr.label(mandatory = True),
    },
)

def _runtime(ctx):
    for file in ctx.files.files:
        if not file.path.startswith(ctx.executable.dotnet.dirname + "/"):
            fail("SDK artifacts must be rooted beside dotnet: " + file.path)
    output = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    args = ctx.actions.args()
    args.add(ctx.executable.dotnet.dirname)
    args.add(output.path)
    files = [file for file in ctx.files.files if not ctx.attr.runtime_only or file == ctx.executable.dotnet or file.path[len(ctx.executable.dotnet.dirname) + 1:].split("/")[0] in ["host", "shared"]]
    args.add_all(files)
    args.set_param_file_format("multiline")
    args.use_param_file("%s", use_always = True)
    ctx.actions.run_shell(
        inputs = files,
        outputs = [output],
        arguments = [args],
        command = """set -eu
exec 3< "$1"
IFS= read -r root <&3
IFS= read -r output <&3
root="${root%$'\\r'}/"
output="${output%$'\\r'}"
mkdir -p "$output"
while IFS= read -r file <&3; do
    file="${file%$'\\r'}"
    relative="${file#"$root"}"
    test "$relative" != "$file"
    mkdir -p "$output/$(dirname "$relative")"
    cp -pL "$file" "$output/$relative"
done
""",
        mnemonic = "DotnetSdkRuntime",
    )
    return [DefaultInfo(files = depset([output])), MSBuildRuntimeInfo(
        directory = output,
        entry_point = ctx.executable.dotnet.basename,
        launch_mode = "dotnet",
        runtime_identifier = ctx.attr.runtime_identifier,
        version = ctx.attr.version,
        environment = {},
        files = depset([output]),
    )]

sdk_runtime = rule(
    implementation = _runtime,
    attrs = {
        "dotnet": attr.label(allow_single_file = True, executable = True, cfg = "target", mandatory = True),
        "files": attr.label(mandatory = True),
        "runtime_only": attr.bool(default = False),
        "runtime_identifier": attr.string(mandatory = True),
        "version": attr.string(mandatory = True),
    },
)

def _runtime_toolchain(ctx):
    return [platform_common.ToolchainInfo(runtime = ctx.attr.runtime[MSBuildRuntimeInfo])]

sdk_runtime_toolchain = rule(
    implementation = _runtime_toolchain,
    attrs = {"runtime": attr.label(providers = [MSBuildRuntimeInfo], mandatory = True)},
)
