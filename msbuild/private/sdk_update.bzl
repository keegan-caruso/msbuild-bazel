"""Executable SDK maintenance target, requiring neither an SDK nor shell rules."""

def _update(ctx):
    executable = ctx.actions.declare_file(ctx.label.name + ".launcher.sh")
    ctx.actions.expand_template(
        template = ctx.file.script,
        output = executable,
        substitutions = {},
        is_executable = True,
    )
    return [DefaultInfo(executable = executable)]

sdk_update = rule(
    implementation = _update,
    executable = True,
    attrs = {"script": attr.label(allow_single_file = True, mandatory = True)},
)
