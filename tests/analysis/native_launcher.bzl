"""Portable analysis controls for the native Bash launcher contract."""

load("@rules_shell//shell/toolchains:sh_toolchain.bzl", "sh_toolchain")
load("@rules_testing//lib:analysis_test.bzl", "analysis_test")
load("@rules_testing//lib:truth.bzl", "matching")
load("@rules_testing//lib:util.bzl", "TestingAspectInfo")

# buildifier: disable=bzl-visibility
load("//msbuild/private:shell_launcher.bzl", "SHELL_TOOLCHAIN", "shell_launcher", "shell_launcher_attrs")
load(":helpers.bzl", "action")

ScriptInfo = provider(fields = ["file"])

def _probe(ctx):
    script = ctx.file.script
    if not script:
        script = ctx.actions.declare_file(ctx.label.name + " script.sh")
        ctx.actions.write(script, "#!/usr/bin/env bash\nexit 0\n", is_executable = True)
    executable = shell_launcher(ctx, script)
    return [DefaultInfo(executable = executable, runfiles = ctx.runfiles(files = [script, executable])), ScriptInfo(file = script)]

probe = rule(
    implementation = _probe,
    attrs = dict(shell_launcher_attrs(), script = attr.label(allow_single_file = True)),
    executable = True,
    toolchains = [config_common.toolchain_type(SHELL_TOOLCHAIN, mandatory = False)],
)

def _windows(env, target):
    generated = action(target, "MSBuildShellLauncher")
    script = target[ScriptInfo].file
    executable = target[DefaultInfo].files_to_run.executable
    env.expect.that_str(executable.extension).equals("exe")
    env.expect.that_collection(generated.argv).contains_at_least([
        "binary_type=Bash",
        "workspace_name=_main",
        "symlink_runfiles_enabled=0",
        "bash_bin_path=C:/Program Files/Git/bin/bash.exe",
        "bash_file_rlocationpath=" + (script.short_path[3:] if script.short_path.startswith("../") else "_main/" + script.short_path),
    ])
    env.expect.that_collection(target[DefaultInfo].default_runfiles.files.to_list()).contains_at_least([script, executable])
    env.expect.that_collection([file.basename for file in generated.inputs.to_list()]).contains("launcher-template.txt")

def _unix(env, target):
    env.expect.that_str(target[DefaultInfo].files_to_run.executable.path).equals(target[ScriptInfo].file.path)
    env.expect.that_collection([item.mnemonic for item in target[TestingAspectInfo].actions]).not_contains("MSBuildShellLauncher")

def native_launcher_tests(name):
    native.platform(name = name + "_windows", constraint_values = ["@platforms//os:windows", "@platforms//cpu:x86_64"])
    native.platform(name = name + "_unix", constraint_values = ["@platforms//os:linux", "@platforms//cpu:x86_64"])
    sh_toolchain(name = name + "_shell", path = "C:/Program Files/Git/bin/bash.exe", launcher = ":launcher-template.txt", launcher_maker = ":dotnet", tags = ["manual"])
    native.toolchain(name = name + "_toolchain", toolchain = ":" + name + "_shell", toolchain_type = SHELL_TOOLCHAIN)
    sh_toolchain(name = name + "_missing_shell", path = "C:/bash.exe", tags = ["manual"])
    native.toolchain(name = name + "_missing_toolchain", toolchain = ":" + name + "_missing_shell", toolchain_type = SHELL_TOOLCHAIN)
    probe(name = name + "_generated", tags = ["manual"])

    # An inert external file exercises repository-relative lookup; no launcher executes.
    probe(name = name + "_external", script = "@platforms//:LICENSE", tags = ["manual"])
    settings = {"//command_line_option:platforms": str(Label(":" + name + "_windows")), "//command_line_option:extra_toolchains": [str(Label(":" + name + "_toolchain"))], "//command_line_option:enable_runfiles": "no"}
    for suffix in ["generated", "external"]:
        analysis_test(name = name + "_" + suffix + "_test", target = ":" + name + "_" + suffix, config_settings = settings, impl = _windows)

    # The launcher policy stays manifest-first even when a symlink tree exists.
    symlinks = dict(settings)
    symlinks["//command_line_option:enable_runfiles"] = "yes"
    analysis_test(name = name + "_symlinks_test", target = ":" + name + "_generated", config_settings = symlinks, impl = _windows)
    analysis_test(name = name + "_unix_test", target = ":" + name + "_generated", config_settings = {"//command_line_option:platforms": str(Label(":" + name + "_unix"))}, impl = _unix)
    missing = dict(settings)
    missing["//command_line_option:extra_toolchains"] = [str(Label(":" + name + "_missing_toolchain"))]
    analysis_test(name = name + "_missing_test", target = ":" + name + "_generated", config_settings = missing, expect_failure = True, impl = lambda env, subject: env.expect.that_target(subject).failures().contains_predicate(matching.contains("require a shell toolchain")))
    native.test_suite(name = name, tests = [name + "_" + suffix + "_test" for suffix in ["generated", "external", "symlinks", "unix", "missing"]])
