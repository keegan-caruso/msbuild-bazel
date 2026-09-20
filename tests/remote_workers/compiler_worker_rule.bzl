"""Exercise production worker protocol with pre-bound, package-free test plans."""

def _compile(ctx):
    fields = {name: ctx.actions.declare_directory(ctx.label.name + "." + name) for name in ["output", "apiOutput", "runtimeOutput", "diagnostics"]}
    request = ctx.actions.declare_file(ctx.label.name + ".request.json")

    # The request includes arrays/bools as well as path strings.
    value = json.decode(ctx.attr.request_json) | {name: f.path for name, f in fields.items()}
    ctx.actions.write(request, json.encode(value))
    args = ctx.actions.args()
    args.add(request.path)
    args.use_param_file("@%s", use_always = True)
    args.set_param_file_format("multiline")
    ctx.actions.run(
        executable = ctx.executable.dotnet,
        arguments = [ctx.file.runner.path, "--bazel-worker", args],
        inputs = ctx.files.srcs + [request],
        tools = ctx.files.support + [ctx.file.runner],
        outputs = fields.values(),
        mnemonic = "CompilerWorkerProbe",
        execution_requirements = {"supports-workers": "1", "requires-worker-protocol": "json", "no-remote-exec": "1"},
    )
    return [DefaultInfo(files = depset(fields.values()))]

compile = rule(implementation = _compile, attrs = {
    "request_json": attr.string(),
    "srcs": attr.label_list(allow_files = True),
    "support": attr.label_list(allow_files = True),
    "runner": attr.label(allow_single_file = True),
    "dotnet": attr.label(executable = True, cfg = "exec", allow_single_file = True),
})
