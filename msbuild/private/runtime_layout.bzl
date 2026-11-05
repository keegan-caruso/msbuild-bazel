"""Compose a shared framework from declared graph and native outputs."""

load("//msbuild:graph.bzl", "MSBuildGraphInfo")
load(":paths.bzl", _TOOLCHAIN = "TOOLCHAIN")
load(":providers.bzl", "MSBuildLayoutInfo")

def _safe(value):
    if not value or value.startswith("/") or "\\" in value or any([part in ["", ".", ".."] for part in value.split("/")]):
        fail("Runtime layout requires a safe relative path: " + value)
    return value

def _runtime_layout(ctx):
    graph = ctx.attr.graph[MSBuildGraphInfo]
    shared = "shared/" + _safe(ctx.attr.framework_name) + "/" + _safe(ctx.attr.version)
    if "/" in ctx.attr.framework_name or "/" in ctx.attr.version:
        fail("Framework name and version must be single path components")
    if not ctx.attr.projects:
        fail("Runtime layout requires explicit configured projects")
    selections = []
    managed = {}
    for key in ctx.attr.projects:
        if key not in graph.projects:
            fail("Unknown runtime graph project: " + key)
        directory, assembly, kind = graph.projects[key]
        if kind != "Library" or not assembly.endswith(".dll") or "/" in assembly:
            fail("Runtime projects must produce library assemblies: " + key)
        if assembly in managed:
            fail("Duplicate runtime assembly: " + assembly)
        project, framework = key.rsplit("|", 1)
        managed[assembly] = {"project": project, "framework": framework, "path": _safe(directory) + "/" + _safe(assembly)}
        selections.append(("workspace/" + directory + "/", assembly))

    def entries(file, expander):
        children = {child.path[len(file.path) + 1:]: child for child in expander.expand(file)}
        result = []
        for prefix, assembly in selections:
            required = prefix + assembly
            result.append(json.encode({"source": file.path + "/" + required, "path": shared + "/" + assembly}))
            for relative, child in children.items():
                if relative.startswith(prefix) and relative != required:
                    result.append(json.encode({"source": child.path, "path": shared + "/" + relative[len(prefix):]}))
        return result

    args = ctx.actions.args()
    args.use_param_file("@%s", use_always = True)
    args.set_param_file_format("multiline")
    args.add_all([graph.directory], map_each = entries, expand_directories = False, allow_closure = True)
    native = {}
    destinations = {}
    for target, path in ctx.attr.native.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Native runtime members require one declared file per label")
        file = files[0]
        if file.basename in native or path in destinations:
            fail("Duplicate native runtime member: " + path)
        native[file.basename] = {"label": str(target.label), "path": _safe(path)}
        destinations[path] = True
        args.add(json.encode({"source": file.path, "path": path}))
    for target, path in ctx.attr.data.items():
        files = target[DefaultInfo].files.to_list()
        if len(files) != 1 or files[0].is_directory:
            fail("Runtime data requires one declared file per label")
        args.add(json.encode({"source": files[0].path, "path": _safe(path)}))
    output = ctx.actions.declare_directory(ctx.label.name + ".layout")
    request = ctx.actions.declare_file(ctx.label.name + ".runtime-layout.json")
    provenance = json.decode(ctx.attr.provenance)
    if type(provenance) != "dict":
        fail("Runtime provenance must be a JSON object")
    ctx.actions.write(request, json.encode({
        "output": output.path,
        "shared": shared,
        "frameworkName": ctx.attr.framework_name,
        "version": ctx.attr.version,
        "targetFramework": ctx.attr.target_framework,
        "targetFrameworkMoniker": ctx.attr.target_framework_moniker,
        "runtimeIdentifier": ctx.attr.runtime_identifier,
        "buildId": ctx.attr.build_id,
        "buildInfo": _safe(ctx.attr.build_info),
        "graphContract": graph.contract.path,
        "managed": managed,
        "native": native,
        "provenance": provenance,
    }))
    tc = ctx.toolchains[_TOOLCHAIN]
    ctx.actions.run(
        executable = tc.dotnet,
        arguments = [tc.runner.path, "runtime-layout", request.path, args],
        inputs = depset([graph.directory, graph.contract, request, tc.runner] + ctx.files.native + ctx.files.data, transitive = [tc.runtime, tc.runner_support]),
        outputs = [output],
        mnemonic = "MSBuildRuntimeLayout",
    )
    return [DefaultInfo(files = depset([output])), MSBuildLayoutInfo(directory = output)]

msbuild_runtime_layout = rule(
    implementation = _runtime_layout,
    attrs = {
        "graph": attr.label(providers = [MSBuildGraphInfo], mandatory = True),
        "projects": attr.string_list(mandatory = True),
        "native": attr.label_keyed_string_dict(allow_files = True),
        "data": attr.label_keyed_string_dict(allow_files = True),
        "framework_name": attr.string(default = "Microsoft.NETCore.App"),
        "version": attr.string(mandatory = True),
        "target_framework": attr.string(mandatory = True),
        "target_framework_moniker": attr.string(mandatory = True),
        "runtime_identifier": attr.string(mandatory = True),
        "build_id": attr.string(),
        "build_info": attr.string(default = "runtime-build.json"),
        "provenance": attr.string(default = "{}", doc = "JSON build facts; graph and producer identities are added by the action."),
    },
    toolchains = [_TOOLCHAIN],
)
