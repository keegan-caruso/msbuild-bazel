"""Bounded Bazel/MSBuild project-cache experiment for synthetic project graphs."""

def _probe_binary(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".payload")
    ctx.actions.run_shell(
        inputs = depset(ctx.files.sources, transitive = [ctx.attr.sdk[DefaultInfo].files]),
        tools = [ctx.executable.dotnet],
        outputs = [output],
        arguments = [ctx.executable.dotnet.path, ctx.file.project.path, output.path],
        command = """set -eu
dotnet="$PWD/$1"; project="$PWD/$2"; output="$PWD/$3"
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
"$dotnet" build "$project" -c Release -o "$output" --nologo \
    -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \
    -p:RestoreSources="$scratch/empty" -p:NuGetAudit=false
""",
        mnemonic = "MSBuildCacheProbeBootstrap",
    )
    return [DefaultInfo(files = depset([output]))]

probe_binary = rule(
    implementation = _probe_binary,
    attrs = {
        "dotnet": attr.label(executable = True, cfg = "exec", allow_single_file = True, mandatory = True),
        "sdk": attr.label(mandatory = True),
        "project": attr.label(allow_single_file = True, mandatory = True),
        "sources": attr.label(mandatory = True),
    },
)

def _graph_group(ctx):
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
    prefix = ctx.attr.source_root + "/"
    args = ctx.actions.args()
    args.add(ctx.executable.dotnet.path)
    args.add(payloads[0].path)
    args.add(output.path)
    args.add(ctx.attr.entry)
    args.add(seed.path if seed else "-")
    args.add(ctx.file.global_json.path)
    for source in ctx.files.srcs:
        if not source.short_path.startswith(prefix):
            fail("source is outside " + ctx.attr.source_root + ": " + source.short_path)
        args.add(source.path)
        args.add(source.short_path[len(prefix):])
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + [ctx.file.global_json, payloads[0]] + ([seed] if seed else []), transitive = [ctx.attr.sdk[DefaultInfo].files]),
        tools = [ctx.executable.dotnet],
        outputs = [output],
        arguments = [args],
        command = """set -eu
dotnet="$PWD/$1"; probe="$PWD/$2"; output="$PWD/$3"; entry="$4"; seed="$5"; global_json="$PWD/$6"
shift 6
workspace="$output/workspace"
mkdir -p "$workspace" "$output/empty" "$output/home"
cp "$global_json" "$workspace/global.json"
while test "$#" -gt 0; do
    source="$PWD/$1"; relative="$2"; shift 2
    mkdir -p "$workspace/$(dirname "$relative")"
    cp "$source" "$workspace/$relative"
done
if test "$seed" != "-"; then seed="$PWD/$seed/cache"; fi
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$output/home" HOME="$output/home"
export DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
export MSBUILDDISABLENODEREUSE=1
"$dotnet" restore "$workspace/$entry" --source "$output/empty" -p:NuGetAudit=false > "$output/restore.log" 2>&1 || {
    cat "$output/restore.log"; exit 1;
}
"$dotnet" exec "$probe/CacheProbe.dll" "$workspace" "$entry" "$seed" "$output/cache" > "$output/run.log" 2>&1 || {
    cat "$output/run.log"; exit 1;
}
""",
        mnemonic = "MSBuildCacheGraphGroup",
    )
    return [DefaultInfo(files = depset([output]))]

graph_group = rule(
    implementation = _graph_group,
    attrs = {
        "dotnet": attr.label(executable = True, cfg = "exec", allow_single_file = True, mandatory = True),
        "sdk": attr.label(mandatory = True),
        "probe": attr.label(mandatory = True),
        "global_json": attr.label(allow_single_file = True, mandatory = True),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "source_root": attr.string(mandatory = True),
        "entry": attr.string(mandatory = True),
        "seed": attr.label(),
    },
)
