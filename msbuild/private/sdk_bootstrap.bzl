"""SDK-only bootstrap actions; deliberately independent of MSBuild toolchains."""

load(":providers.bzl", "MSBuildRuntimeInfo")

_RUNNER_FILES = [
    "ExplicitBuild.dll",
    "ExplicitBuild.deps.json",
    "ExplicitBuild.runtimeconfig.json",
    "Microsoft.Build.Framework.dll",
    "Microsoft.Build.Utilities.Core.dll",
    "Microsoft.Build.dll",
    "Microsoft.NET.StringTools.dll",
    "Microsoft.VisualStudio.SolutionPersistence.dll",
    "NuGet.Frameworks.dll",
    "NuGet.Versioning.dll",
    "System.Configuration.ConfigurationManager.dll",
    "System.Diagnostics.EventLog.dll",
    "System.Security.Cryptography.ProtectedData.dll",
]

def _runner(ctx):
    outputs = [ctx.actions.declare_file(ctx.label.name + "/" + name) for name in _RUNNER_FILES]
    ctx.actions.run_shell(
        inputs = depset(ctx.files.sources + ctx.files.sdk),
        tools = [ctx.executable.dotnet],
        outputs = outputs,
        arguments = [ctx.executable.dotnet.path, ctx.file.project.path, outputs[0].dirname],
        command = """set -eu
dotnet="$PWD/$1"
project="$PWD/$2"
output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export DOTNET_GENERATE_ASPNET_CERTIFICATE=false
export DOTNET_MULTILEVEL_LOOKUP=0 NUGET_PACKAGES="$scratch/packages"
cd "$scratch"
"$dotnet" build "$project" -c Release -o "$output" --nologo \\
    -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \\
    -p:RestoreSources="$scratch/empty" -p:NuGetAudit=false -p:DebugType=None
""",
        mnemonic = "MSBuildRunnerBootstrap",
    )
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
    output = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    args = ctx.actions.args()
    args.add(ctx.executable.dotnet.dirname)
    args.add(output.path)
    args.add_all(ctx.files.files)
    ctx.actions.run_shell(
        inputs = ctx.files.files,
        outputs = [output],
        arguments = [args],
        command = """set -eu
root="$1/"; output="$2"; shift 2
mkdir -p "$output"
for file in "$@"; do
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
        entry_point = "dotnet",
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
