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
    sdk_version = ctx.attr.sdk_version
    sdk_files = ctx.attr.sdk_files
    sdk_directories = ctx.attr.sdk_directories
    if bool(sdk_version) != bool(sdk_files or sdk_directories):
        fail("sdk_version and exact sdk_files/sdk_directories inventory must be supplied together")
    sdk_names = sdk_files + sdk_directories
    for name in [sdk_version] + sdk_names if sdk_version else []:
        if not name or name in [".", ".."]:
            fail("SDK inventory names must be single path components: " + name)
        for index in range(len(name)):
            if name[index] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-":
                fail("Invalid SDK inventory name: " + name)
    if len(sdk_names) != len({name: True for name in sdk_names}):
        fail("SDK inventory names must be unique")
    if sdk_version:
        for name in ["DotnetTools", "FSharp"]:
            if name not in sdk_directories:
                fail("Split SDK inventory must include directory " + name)
        files += [ctx.actions.declare_file(ctx.label.name + "/sdk/" + sdk_version + "/" + name) for name in sdk_files]
    pack_names = ctx.attr.pack_names
    for name in pack_names:
        if not name or name in [".", ".."]:
            fail("Pack names must be single path components: " + name)
        for index in range(len(name)):
            if name[index] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-":
                fail("Pack names must contain only letters, digits, dot, underscore or hyphen: " + name)
    if len(pack_names) != len({name: True for name in pack_names}):
        fail("Pack names must be unique")
    for name in ctx.attr.native_aot_packs:
        if name not in pack_names:
            fail("NativeAOT packs must be declared in pack_names: " + name)
    shared = ["shared/Microsoft.NETCore.App", "shared/Microsoft.AspNetCore.App"] if ctx.attr.split_frameworks else ["shared"]
    directory_names = ["host"] + shared + (["sdk/" + sdk_version + "/" + name for name in sdk_directories] if sdk_version else ["sdk"]) + ["sdk-manifests", "templates", "library-packs", "metadata"] + (["packs/" + name for name in pack_names] if pack_names else ["packs"])
    directories = [ctx.actions.declare_directory(ctx.label.name + "/" + name) for name in directory_names]
    managed_directories = [directory for name, directory in zip(directory_names, directories) if name not in ["packs/" + pack for pack in ctx.attr.native_aot_packs] + (["sdk/" + sdk_version + "/DotnetTools", "sdk/" + sdk_version + "/FSharp"] if sdk_version else [])]
    host = directories[0]
    frameworks = directories[1:1 + len(shared)]
    ctx.actions.run_shell(
        inputs = [ctx.file.archive] + ctx.files.packages,
        outputs = files + directories,
        arguments = [ctx.file.archive.path, dotnet.dirname, "split" if ctx.attr.split_frameworks else "full", " ".join(pack_names), sdk_version, " ".join(sdk_files), " ".join(sdk_directories)] + [value for package, destination in ctx.attr.packages.items() for value in [package.files.to_list()[0].path, destination]],
        command = """set -eu
archive="$1"; root="$2"; framework_mode="$3"; declared_packs="$4"; sdk_version="$5"; sdk_files="$6"; sdk_directories="$7"; shift 7
mkdir -p "$root"
tar --no-same-owner -xzf "$archive" -C "$root"
for directory in host shared sdk packs sdk-manifests templates library-packs metadata; do mkdir -p "$root/$directory"; done
while test "$#" -gt 0; do
    package="$1"; destination="$2"; shift 2
    python3 -m zipfile -e "$package" "$root/$destination"
done
if test "$framework_mode" = split || test -n "$declared_packs" || test -n "$sdk_version"; then
python3 - "$root" "$framework_mode" "$declared_packs" "$sdk_version" "$sdk_files" "$sdk_directories" <<'PYTHON'
from pathlib import Path
import sys
root = Path(sys.argv[1])
def check(directory, expected):
    children = {entry.name: entry for entry in (root / directory).iterdir()}
    if set(children) != set(expected):
        raise ValueError("Unexpected " + directory + " inventory: " + repr(sorted(children)))
    if any(not entry.is_dir() or entry.is_symlink() for entry in children.values()):
        raise ValueError("Expected ordinary directories in " + directory)
if sys.argv[2] == "split":
    check("shared", ["Microsoft.NETCore.App", "Microsoft.AspNetCore.App"])
if sys.argv[3]:
    check("packs", sys.argv[3].split())
if sys.argv[4]:
    version = sys.argv[4]
    check("sdk", [version])
    sdk = root / "sdk" / version
    files, directories = sys.argv[5].split(), sys.argv[6].split()
    children = {entry.name: entry for entry in sdk.iterdir()}
    if set(children) != set(files + directories):
        raise ValueError("Unexpected SDK inventory: " + repr(sorted(children)))
    for name, entry in children.items():
        if entry.is_symlink() or (not entry.is_file() if name in files else not entry.is_dir()):
            raise ValueError("Unexpected SDK entry type: " + name)
PYTHON
fi
""",
        mnemonic = "SourceSdkLayout",
    )
    groups = {"dotnet": depset([dotnet]), "managed": depset(files + managed_directories)}
    if ctx.attr.split_frameworks:
        groups["core_runtime"] = depset([dotnet, host, frameworks[0]])
    return [DefaultInfo(files = depset(files + directories)), OutputGroupInfo(**groups)]

sdk_layout = rule(implementation = _sdk_layout, attrs = {"sdk_version": attr.string(doc = "Version directory for an exact SDK inventory split."), "sdk_files": attr.string_list(doc = "Exact immediate regular file inventory in sdk_version."), "sdk_directories": attr.string_list(doc = "Exact immediate directory inventory in sdk_version; DotnetTools and FSharp are omitted only from managed."), "split_frameworks": attr.bool(), "archive": attr.label(allow_single_file = [".tar.gz"], mandatory = True, cfg = "exec"), "packages": attr.label_keyed_string_dict(allow_files = [".nupkg"]), "pack_names": attr.string_list(doc = "Exact pack directory inventory; empty preserves the complete packs tree."), "native_aot_packs": attr.string_list(doc = "Declared pack directories omitted only from the managed output group.")})
