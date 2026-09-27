"""Qualification component actions with explicit transitive output bundles."""

load(":source_action.bzl", "NativeDriverInfo")

ComponentInfo = provider("Own and transitive upstream component output archives.", fields = ["archives"])

def _component(ctx):
    driver = ctx.attr.driver[NativeDriverInfo]
    dependencies = depset(transitive = [dep[ComponentInfo].archives for dep in ctx.attr.deps])
    output = ctx.actions.declare_file(ctx.label.name + ".generated/component.tar")
    evidence = ctx.actions.declare_file(ctx.label.name + ".generated/result.tar")
    arguments = [driver.directory.path + "/Driver.dll", ctx.file.sandbox.path, ctx.file.native_tools.path, ctx.file.sources.path, "/source/build-native.sh", evidence.path, output.path, "--bootstrap", ctx.file.bootstrap.path, "--script-file", ctx.file.script.path]
    for dependency in dependencies.to_list():
        arguments.extend(["--dependency", dependency.path])
    ctx.actions.run(
        executable = driver.runtime.directory.path + "/dotnet",
        arguments = arguments,
        inputs = depset([driver.directory, ctx.file.sandbox, ctx.file.native_tools, ctx.file.sources, ctx.file.bootstrap, ctx.file.script], transitive = [driver.runtime.files, dependencies]),
        outputs = [output, evidence],
        mnemonic = "SourceComponentBuild",
        execution_requirements = {"no-sandbox": "1", "no-remote-exec": "1", "block-network": "1"},
        env = {"LANG": "C.UTF-8"},
    )
    return [DefaultInfo(files = depset([output])), ComponentInfo(archives = depset([output], transitive = [dependencies])), OutputGroupInfo(evidence = depset([evidence]))]

source_component = rule(
    implementation = _component,
    attrs = {
        "driver": attr.label(providers = [NativeDriverInfo], cfg = "exec", mandatory = True),
        "deps": attr.label_list(providers = [ComponentInfo]),
        "sandbox": attr.label(allow_single_file = True, mandatory = True),
        "native_tools": attr.label(allow_single_file = True, mandatory = True),
        "sources": attr.label(allow_single_file = True, mandatory = True),
        "bootstrap": attr.label(allow_single_file = True, mandatory = True),
        "script": attr.label(allow_single_file = True, mandatory = True),
    },
)

def _package_archive(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".nupkg")
    ctx.actions.run_shell(
        inputs = [ctx.file.component],
        outputs = [output],
        arguments = [ctx.file.component.path, ctx.attr.member, output.path],
        command = 'tar -xOf "$1" -- "$2" > "$3"',
        mnemonic = "SourceComponentPackage",
    )
    return [DefaultInfo(files = depset([output]))]

component_package = rule(
    implementation = _package_archive,
    attrs = {
        "component": attr.label(allow_single_file = [".tar"], mandatory = True),
        "member": attr.string(mandatory = True),
    },
)
