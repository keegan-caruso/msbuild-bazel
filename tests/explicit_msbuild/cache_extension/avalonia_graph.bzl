"""Test-only grouped Avalonia action using declared source and NuGet archives."""

def _avalonia_group(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".group")
    payloads = ctx.attr.probe[DefaultInfo].files.to_list()
    if len(payloads) != 1:
        fail("probe must provide one payload directory")
    seed = None
    if ctx.attr.seed:
        seeds = ctx.attr.seed[DefaultInfo].files.to_list()
        if len(seeds) != 1:
            fail("seed must provide one group directory")
        seed = seeds[0]
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + ctx.files.archives + payloads + ([seed] if seed else []), transitive = [ctx.attr.sdk[DefaultInfo].files]),
        tools = [ctx.executable.dotnet],
        outputs = [output],
        arguments = [ctx.executable.dotnet.path, payloads[0].path, output.path, seed.path if seed else "-", ctx.attr.source_root],
        command = """set -eu
dotnet="$PWD/$1"; probe="$PWD/$2"; output="$PWD/$3"; seed="$4"; source_root="$5"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
workspace="$output/workspace"
mkdir -p "$workspace" "$output/archives" "$scratch/home" "$scratch/packages"
cp -RL "$PWD/$source_root/." "$workspace/"
cp "$PWD/locked-packages/"*.nupkg "$output/archives/"
if test "$seed" != "-"; then seed="$PWD/$seed/cache"; fi
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_HOST_PATH="$dotnet"
export DOTNET_CLI_HOME="$scratch/home" HOME="$scratch/home" NUGET_PACKAGES="$scratch/packages"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export MSBUILDDISABLENODEREUSE=1 NUGET_HTTP_CACHE_PATH="$scratch/http-cache"
"$dotnet" restore "$workspace/src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj" \
  --source "$output/archives" -p:AvsSkipBuildingLegacyTargetFrameworks=True \
  -p:NuGetAudit=false -p:RestorePackagesPath="$scratch/packages" > "$output/restore.log" 2>&1 || {
    cat "$output/restore.log"; exit 1;
}
"$dotnet" exec "$probe/AvaloniaProbe.dll" "$workspace" \
  src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj "$seed" \
  "$output/cache" "$output/report.json" > "$output/build.log" 2>&1 || {
    cat "$output/build.log"; exit 1;
}
""",
        mnemonic = "AvaloniaCacheGraphGroup",
    )
    return [DefaultInfo(files = depset([output]))]

avalonia_group = rule(
    implementation = _avalonia_group,
    attrs = {
        "dotnet": attr.label(executable = True, cfg = "exec", allow_single_file = True, mandatory = True),
        "sdk": attr.label(mandatory = True),
        "probe": attr.label(mandatory = True),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "archives": attr.label_list(allow_files = True, mandatory = True),
        "source_root": attr.string(mandatory = True),
        "seed": attr.label(),
    },
)
