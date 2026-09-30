"""Opt-in MSBuild traversal graph actions with explicit project contracts."""

load("//msbuild/private:graph_tools.bzl", "graph_tool_closure")
load("//msbuild/private:paths.bzl", _RUNTIME_TOOLCHAIN = "RUNTIME_TOOLCHAIN", _TOOLCHAIN = "TOOLCHAIN")
load("//msbuild/private:project_launch.bzl", _create_launcher = "create_launcher")
load("//msbuild/private:providers.bzl", "MSBuildBindingInfo", "MSBuildLayoutInfo", "MSBuildPackageLockInfo", "MSBuildRuntimeInfo")
load("//msbuild/private:test_options.bzl", _TEST_OPTIONS_ATTRS = "TEST_OPTIONS_ATTRS", _validate_test = "validate_test")

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
repository="$(dirname "$(dirname "$(dirname "$project")")")"
mkdir -p "$scratch/empty"
export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1
"$dotnet" build "$project" -c Release -o "$output" --nologo \
  -p:BaseIntermediateOutputPath="$scratch/obj/" -p:UseSharedCompilation=false \
  -p:PathMap="$repository=/_/rules_msbuild%2C$scratch=/_/bootstrap" \
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

MSBuildGraphRestoreInfo = provider("An explicitly declared offline Restore artifact.", fields = ["directory", "contract", "runner", "sdk"])

def _graph_action(ctx, prepare = False):
    tc = ctx.toolchains["//msbuild:toolchain_type"]
    output = ctx.actions.declare_directory(ctx.label.name + (".restore" if prepare else ".graph"))
    runner = ctx.attr.runner[DefaultInfo].files.to_list()
    if len(runner) != 1:
        fail("runner must provide one graph runner payload")
    prepared = ctx.attr.restore[MSBuildGraphRestoreInfo] if ctx.attr.restore else None
    if prepare and prepared:
        fail("Restore preparation cannot consume another Restore artifact")
    if (prepare or prepared) and not ctx.attr.linux_stable_paths:
        fail("Prepared Restore requires linux_stable_paths for relocation")
    if prepared and (prepared.contract != ctx.file.contract or prepared.runner != runner[0] or sorted([file.path for file in prepared.sdk.to_list()]) != sorted([file.path for file in tc.sdk.to_list()])):
        fail("Prepared Restore must use the graph's contract, runner and SDK")
    if ctx.attr.linux_worker and (prepare or not ctx.attr.linux_stable_paths):
        fail("Graph workers require linux_stable_paths and build actions")
    worker_sources = []
    prefix = ctx.attr.source_root + "/" if ctx.attr.source_root else ""
    args = ctx.actions.args()
    args.add_all([tc.dotnet.path, runner[0].path, output.path, ctx.file.contract.path, ctx.attr.target, "1" if ctx.attr.linux_stable_paths else "0", ctx.file._linux_stable_paths.path, "prepare" if prepare else "action", prepared.directory.path if prepared else "-"])
    for file in ctx.files.srcs:
        if not file.short_path.startswith(prefix):
            fail("Graph source is outside source_root: " + file.short_path)
        relative = file.short_path[len(prefix):]
        if relative.startswith("/") or any([part in ["", ".", ".."] for part in relative.split("/")]):
            fail("Graph source requires a safe workspace-relative destination: " + relative)
        args.add_all([file.path, relative])
        worker_sources.append({"path": file.path, "destination": relative})
    for target, relative in ctx.attr.input_paths.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Graph input_paths requires one file per label")
        if relative.startswith("/") or "\\" in relative or any([part in ["", ".", ".."] for part in relative.split("/")]):
            fail("Graph input_paths requires safe workspace-relative paths")
        args.add_all([files[0].path, relative])
        worker_sources.append({"path": files[0].path, "destination": relative})
    closures = []
    tool_properties = {}
    for index, target in enumerate(ctx.attr.bindings):
        binding = target[MSBuildBindingInfo]
        if binding.property_name in tool_properties:
            fail("Duplicate graph tool property: " + binding.property_name)
        tool_properties[binding.property_name] = ".graph-tools/" + str(index) + "/" + binding.tool.entry_point
        closure = graph_tool_closure(ctx, tc, binding, index)
        closures.append(closure)
        args.add_all([closure.path, ".graph-tools/" + str(index)])
        worker_sources.append({"path": closure.path, "destination": ".graph-tools/" + str(index)})
    if closures:
        bindings = ctx.actions.declare_file(ctx.label.name + ".graph-bindings.json")
        ctx.actions.write(bindings, json.encode(tool_properties))
        closures.append(bindings)
        args.add_all([bindings.path, ".graph-tools/bindings.json"])
        worker_sources.append({"path": bindings.path, "destination": ".graph-tools/bindings.json"})
    packages = depset(ctx.files.packages, transitive = [ctx.attr.package_lock[MSBuildPackageLockInfo].archives] if ctx.attr.package_lock else []).to_list()
    for file in packages:
        args.add_all([file.path, ".package-source/" + file.basename])
        worker_sources.append({"path": file.path, "destination": ".package-source/" + file.basename})
    action_inputs = depset(ctx.files.srcs + [file for target in ctx.attr.input_paths for file in target[DefaultInfo].files.to_list()] + packages + closures + ([prepared.directory] if prepared else []) + [ctx.file.contract, runner[0], ctx.file._linux_stable_paths], transitive = [tc.sdk] + ([ctx.attr.package_lock[MSBuildPackageLockInfo].files] if ctx.attr.package_lock else []))
    if ctx.attr.linux_worker:
        request = ctx.actions.declare_file(ctx.label.name + ".graph-request.json")
        ctx.actions.write(request, json.encode({
            "contract": ctx.file.contract.path,
            "output": output.path,
            "target": ctx.attr.target,
            "prepared": prepared.directory.path if prepared else None,
            "sources": worker_sources,
        }))
        launcher = ctx.actions.declare_file(ctx.label.name + ".graph-worker.sh")
        ctx.actions.write(launcher, "#!/usr/bin/env bash\nset -eu\nexec \"$PWD/%s\" exec \"$PWD/%s/GraphBuild.dll\" worker \"$PWD/%s\" \"$@\"\n" % (tc.dotnet.path, runner[0].path, ctx.file._linux_stable_paths.path), is_executable = True)
        params = ctx.actions.args()
        params.add(request.path)
        params.use_param_file("@%s", use_always = True)
        params.set_param_file_format("multiline")
        ctx.actions.run(
            executable = launcher,
            arguments = [params],
            inputs = depset([request], transitive = [action_inputs]),
            tools = depset([tc.dotnet, runner[0], ctx.file._linux_stable_paths], transitive = [tc.sdk]),
            outputs = [output],
            env = {key: value for key, value in ctx.configuration.default_shell_env.items() if key.startswith("RULES_MSBUILD_PROJECT_CACHE_")},
            execution_requirements = {"supports-workers": "1", "requires-worker-protocol": "json"},
            mnemonic = "MSBuildGraph",
        )
    else:
        ctx.actions.run_shell(
            inputs = action_inputs,
            tools = [tc.dotnet],
            outputs = [output],
            arguments = [args],
            env = {key: value for key, value in ctx.configuration.default_shell_env.items() if key.startswith("RULES_MSBUILD_PROJECT_CACHE_")},
            command = """set -eu
    dotnet="$PWD/$1"; runner="$PWD/$2"; output="$PWD/$3"; contract="$PWD/$4"; target="$5"; isolated="$6"; sandbox="$PWD/$7"; mode="$8"; prepared="$9"
    if test "$prepared" != -; then prepared="$PWD/$prepared"; fi
    shift 9
    scratch=$(mktemp -d)
    trap 'rm -rf "$scratch"' EXIT
    workspace="$output/workspace"
    mkdir -p "$workspace"
    while test "$#" -gt 0; do
        source="$PWD/$1"; relative="$2"; shift 2
        test ! -e "$workspace/$relative"
        mkdir -p "$workspace/$(dirname "$relative")"
        if test -d "$source"; then
            mkdir -p "$workspace/$relative"
            cp -pRL "$source/." "$workspace/$relative/"
        else
            cp -pL "$source" "$workspace/$relative"
        fi
    done
    export DOTNET_ROOT="$(dirname "$dotnet")" DOTNET_CLI_HOME="$scratch" HOME="$scratch"
    export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 DOTNET_NOLOGO=1
    export MSBUILDDISABLENODEREUSE=1
    if test "$isolated" = 1; then
        bash "$sandbox" "$(dirname "$dotnet")" "$runner" "$output" "$contract" "$scratch" "$target" "$mode" "$prepared"
        if test "$mode" = prepare; then rm -rf "$workspace"; rm -f "$output/report.json"; fi
        exit 0
    fi
    "$dotnet" exec "$runner/GraphBuild.dll" action "$workspace" "$contract" "$output/report.json" "$scratch/cache" "$target"
    """,
            mnemonic = "MSBuildGraphRestore" if prepare else "MSBuildGraph",
        )
    if prepare:
        return [DefaultInfo(files = depset([output])), MSBuildGraphRestoreInfo(directory = output, contract = ctx.file.contract, runner = runner[0], sdk = tc.sdk)]
    return [DefaultInfo(files = depset([output])), MSBuildGraphInfo(directory = output, dotnet = tc.dotnet, sdk = tc.sdk, projects = ctx.attr.publish_outputs if ctx.attr.target == "Publish" else ctx.attr.project_outputs)]

def _graph(ctx):
    return _graph_action(ctx)

def _restore(ctx):
    return _graph_action(ctx, prepare = True)

_GRAPH_ATTRS = {
    "restore": attr.label(providers = [MSBuildGraphRestoreInfo]),
    "contract": attr.label(allow_single_file = [".json"], mandatory = True),
    "runner": attr.label(mandatory = True, cfg = "exec"),
    "srcs": attr.label_list(allow_files = True, mandatory = True),
    "bindings": attr.label_list(providers = [MSBuildBindingInfo], cfg = "exec"),
    "input_paths": attr.label_keyed_string_dict(allow_files = True),
    "packages": attr.label_list(allow_files = [".nupkg"]),
    "package_lock": attr.label(providers = [MSBuildPackageLockInfo]),
    "source_root": attr.string(),
    "project_outputs": attr.string_list_dict(),
    "publish_outputs": attr.string_list_dict(),
    "linux_worker": attr.bool(default = False, doc = "Opt-in Linux cache broker; each request runs a fresh sandboxed MSBuild process."),
    "linux_stable_paths": attr.bool(default = False, doc = "Use bubblewrap on Linux for stable graph paths; cache transport retains network access."),
    "_linux_stable_paths": attr.label(default = "//msbuild:graph-sandbox.sh", allow_single_file = True),
    "target": attr.string(default = "Build", values = ["Build", "Publish"]),
}

msbuild_graph = rule(
    implementation = _graph,
    attrs = _GRAPH_ATTRS,
    toolchains = ["//msbuild:toolchain_type"],
)

msbuild_graph_restore = rule(
    implementation = _restore,
    attrs = _GRAPH_ATTRS,
    toolchains = ["//msbuild:toolchain_type"],
)

def _runtime(ctx, test = False):
    graph = ctx.attr.graph[MSBuildGraphInfo]
    assembly = ctx.attr.assembly
    if ctx.attr.project:
        if assembly:
            fail("Use project or assembly, not both")
        candidates = [value for key, value in graph.projects.items() if key.split("|")[0] == ctx.attr.project and (not ctx.attr.framework or key.split("|")[1] == ctx.attr.framework)]
        if len(candidates) != 1:
            fail("Select one generated project/framework with project and framework: " + ctx.attr.project)
        directory, assembly, kind = candidates[0]
        if kind.lower() not in ["exe", "winexe"] and not (test and ctx.attr.test_protocol == "vstest"):
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
        # MSBuild already composed the complete runtime. Empty package manifests
        # tell the shared launcher that no deferred package files remain.
        command = 'set -eu; test -f "$1/$3"; mkdir -p "$2"; cp -pRL "$1/." "$2/"; for name in .rules-msbuild-packages.json .rules-msbuild-package-files.json; do test ! -e "$2/$name"; printf "{}" > "$2/$name"; done',
        mnemonic = "MSBuildGraphRuntime",
    )
    for target in ctx.attr.data_paths:
        if len(target[DefaultInfo].files.to_list()) != 1 or target[DefaultInfo].files.to_list()[0].is_directory:
            fail("data_paths requires one file per label")
    data = depset([struct(file = target[DefaultInfo].files.to_list()[0], destination = path) for target, path in ctx.attr.data_paths.items()])
    return _create_launcher(ctx, ctx.toolchains[_TOOLCHAIN], assembly.removesuffix(".dll"), output, depset(), depset(), data, test)

def _test(ctx):
    _validate_test(ctx)
    return _runtime(ctx, test = True)

_RUNTIME_ATTRS = {
    "graph": attr.label(providers = [MSBuildGraphInfo], mandatory = True),
    "project": attr.string(),
    "framework": attr.string(),
    "assembly": attr.string(),
    "runtime_host": attr.label(providers = [MSBuildRuntimeInfo]),
    "data_paths": attr.label_keyed_string_dict(allow_files = True),
}

msbuild_graph_binary = rule(
    implementation = _runtime,
    attrs = _RUNTIME_ATTRS,
    executable = True,
    toolchains = [_TOOLCHAIN, config_common.toolchain_type(_RUNTIME_TOOLCHAIN, mandatory = False)],
)

msbuild_graph_test = rule(
    implementation = _test,
    attrs = dict(_RUNTIME_ATTRS, **{key: value for key, value in _TEST_OPTIONS_ATTRS.items() if key != "test_output_type"}),
    toolchains = [_TOOLCHAIN, config_common.toolchain_type(_RUNTIME_TOOLCHAIN, mandatory = False)],
    test = True,
)

def _layout(ctx):
    graph = ctx.attr.graph[MSBuildGraphInfo]
    candidates = [value for key, value in graph.projects.items() if key.split("|")[0] == ctx.attr.project and (not ctx.attr.framework or key.split("|")[1] == ctx.attr.framework)]
    if len(candidates) != 1:
        fail("Select one generated project/framework with project and framework: " + ctx.attr.project)
    directory, assembly, _kind = candidates[0]
    for path in [directory, assembly]:
        if path.startswith("/") or "\\" in path or any([part in ["", ".", ".."] for part in path.split("/")]):
            fail("Graph layout requires safe workspace-relative outputs")
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    ctx.actions.run_shell(
        inputs = [graph.directory],
        outputs = [output],
        arguments = [graph.directory.path + "/workspace/" + directory, output.path, assembly],
        command = 'set -eu; test -f "$1/$3"; mkdir -p "$2"; cp -pRL "$1/." "$2/"',
        mnemonic = "MSBuildGraphLayout",
    )
    return [DefaultInfo(files = depset([output])), MSBuildLayoutInfo(directory = output)]

msbuild_graph_layout = rule(
    implementation = _layout,
    attrs = {
        "graph": attr.label(providers = [MSBuildGraphInfo], mandatory = True),
        "project": attr.string(mandatory = True),
        "framework": attr.string(),
    },
)
