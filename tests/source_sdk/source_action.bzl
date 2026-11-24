"""Qualification-only, coarse SDK source producer with declared bootstrap inputs."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo")

NativeDriverInfo = provider("Compiled qualification driver and its execution SDK.", fields = ["runtime", "directory"])

def _compile_driver(ctx):
    bootstrap = ctx.attr.driver_sdk[MSBuildRuntimeInfo]
    driver = ctx.actions.declare_directory(ctx.label.name + ".driver")
    ctx.actions.run_shell(
        inputs = depset([ctx.file.driver_project, ctx.file.driver_source], transitive = [bootstrap.files]),
        outputs = [driver],
        arguments = [bootstrap.directory.path, ctx.file.driver_project.path, driver.path],
        command = """set -eu
dotnet="$PWD/$1/dotnet"; project="$PWD/$2"; output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
export NUGET_PACKAGES="$scratch/packages"
cd "$scratch"
"$dotnet" build "$project" -c Release -o "$output" --nologo \\
    -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \\
    -p:RestoreSources="$scratch/empty" -p:NuGetAudit=false -p:DebugType=None
""",
        mnemonic = "SourceSdkDriver",
    )
    return bootstrap, driver

def _native_driver(ctx):
    bootstrap, driver = _compile_driver(ctx)
    return [DefaultInfo(files = depset([driver])), NativeDriverInfo(runtime = bootstrap, directory = driver)]

native_driver = rule(
    implementation = _native_driver,
    attrs = {
        "driver_sdk": attr.label(providers = [MSBuildRuntimeInfo], mandatory = True, cfg = "exec"),
        "driver_project": attr.label(allow_single_file = True, mandatory = True),
        "driver_source": attr.label(allow_single_file = True, mandatory = True),
    },
)

def _source_sdk(ctx):
    bootstrap, driver = _compile_driver(ctx)
    archive = ctx.actions.declare_file(ctx.label.name + ".generated/sdk.tar.gz")
    evidence = ctx.actions.declare_file(ctx.label.name + ".generated/result.tar")
    ctx.actions.run(
        executable = bootstrap.directory.path + "/dotnet",
        arguments = [driver.path + "/Driver.dll", ctx.file.sandbox.path, ctx.file.native_tools.path, ctx.file.sources.path, "/source/build-native.sh", evidence.path, archive.path, "--bootstrap", ctx.file.bootstrap.path] + (["--system-bwrap"] if ctx.attr.system_bwrap else []),
        inputs = depset([driver, ctx.file.sandbox, ctx.file.native_tools, ctx.file.sources, ctx.file.bootstrap], transitive = [bootstrap.files]),
        outputs = [archive, evidence],
        mnemonic = "SourceSdkBuild",
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1", "block-network": "1"},
        env = {"LANG": "C.UTF-8"},
    )
    return [DefaultInfo(files = depset([archive])), OutputGroupInfo(evidence = depset([evidence]), driver = depset([driver]))]

source_sdk = rule(
    implementation = _source_sdk,
    attrs = {
        "system_bwrap": attr.bool(doc = "Verify and use root-owned packaged /usr/bin/bwrap; no fallback."),
        "driver_sdk": attr.label(providers = [MSBuildRuntimeInfo], mandatory = True, cfg = "exec"),
        "driver_project": attr.label(allow_single_file = True, mandatory = True),
        "driver_source": attr.label(allow_single_file = True, mandatory = True),
        "sandbox": attr.label(allow_single_file = True, mandatory = True),
        "native_tools": attr.label(allow_single_file = True, mandatory = True),
        "sources": attr.label(allow_single_file = True, mandatory = True),
        "bootstrap": attr.label(allow_single_file = True, mandatory = True),
    },
)

def _sdk_layout(ctx):
    dotnet = ctx.actions.declare_file(ctx.label.name + "/dotnet")
    files = [dotnet] + [ctx.actions.declare_file(ctx.label.name + "/" + name) for name in ["dnx", "LICENSE.txt", "ThirdPartyNotices.txt"]]
    host = ctx.actions.declare_directory(ctx.label.name + "/host")
    shared = ["shared/Microsoft.NETCore.App", "shared/Microsoft.AspNetCore.App"] if ctx.attr.split_frameworks else ["shared"]
    frameworks = [ctx.actions.declare_directory(ctx.label.name + "/" + name) for name in shared]
    directories = [host] + frameworks + [ctx.actions.declare_directory(ctx.label.name + "/" + name) for name in ["sdk", "packs", "sdk-manifests", "templates", "library-packs", "metadata"]]
    ctx.actions.run_shell(
        inputs = [ctx.file.archive] + ctx.files.packages,
        outputs = files + directories,
        arguments = [ctx.file.archive.path, dotnet.dirname, "split" if ctx.attr.split_frameworks else "full"] + [value for package, destination in ctx.attr.packages.items() for value in [package.files.to_list()[0].path, destination]],
        command = """set -eu
archive="$1"; root="$2"; framework_mode="$3"; shift 3
mkdir -p "$root"
tar --no-same-owner -xzf "$archive" -C "$root"
if test "$framework_mode" = split; then
    for framework in "$root"/shared/*; do
        case "${framework##*/}" in
            Microsoft.NETCore.App|Microsoft.AspNetCore.App) ;;
            *) echo "Unexpected shared framework: $framework" >&2; exit 1 ;;
        esac
    done
    test -d "$root/shared/Microsoft.NETCore.App"
    test -d "$root/shared/Microsoft.AspNetCore.App"
fi
for directory in host shared sdk packs sdk-manifests templates library-packs metadata; do mkdir -p "$root/$directory"; done
while test "$#" -gt 0; do
    package="$1"; destination="$2"; shift 2
    python3 -m zipfile -e "$package" "$root/$destination"
done
""",
        mnemonic = "SourceSdkLayout",
    )
    groups = {"dotnet": depset([dotnet])}
    if ctx.attr.split_frameworks:
        groups["core_runtime"] = depset([dotnet, host, frameworks[0]])
    return [DefaultInfo(files = depset(files + directories)), OutputGroupInfo(**groups)]

sdk_layout = rule(implementation = _sdk_layout, attrs = {"split_frameworks": attr.bool(), "archive": attr.label(allow_single_file = [".tar.gz"], mandatory = True, cfg = "exec"), "packages": attr.label_keyed_string_dict(allow_files = [".nupkg"])})
