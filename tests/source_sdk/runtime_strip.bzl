"""Qualification-only stripped runtime derivative; retain the original debug tree."""

load("@rules_cc//cc:find_cc_toolchain.bzl", "find_cpp_toolchain", "use_cc_toolchain")
load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo")

def _stripped_runtime(ctx):
    runtime = ctx.attr.runtime[MSBuildRuntimeInfo]
    cc_toolchain = find_cpp_toolchain(ctx)
    output = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    ctx.actions.run_shell(
        inputs = runtime.files,
        tools = cc_toolchain.all_files,
        outputs = [output],
        arguments = [runtime.directory.path, output.path, cc_toolchain.strip_executable],
        command = """python3 - "$@" <<'PYTHON'
import shutil
import subprocess
import sys

source, destination, strip = sys.argv[1:]

def copy_runtime_file(src, dst):
    with open(src, "rb") as stream:
        elf = stream.read(4) == b"\\x7fELF"
    if elf:
        subprocess.run([strip, "--strip-debug", "-o", dst, src], check=True)
        shutil.copymode(src, dst)
    else:
        shutil.copy2(src, dst)

shutil.copytree(source, destination, copy_function=copy_runtime_file, dirs_exist_ok=True)
PYTHON
""",
        mnemonic = "SourceSdkStripRuntime",
    )
    return [DefaultInfo(files = depset([output])), MSBuildRuntimeInfo(
        directory = output,
        entry_point = runtime.entry_point,
        launch_mode = runtime.launch_mode,
        runtime_identifier = runtime.runtime_identifier,
        version = runtime.version,
        environment = runtime.environment,
        files = depset([output]),
    )]

stripped_runtime = rule(
    implementation = _stripped_runtime,
    attrs = {"runtime": attr.label(providers = [MSBuildRuntimeInfo], mandatory = True)},
    toolchains = use_cc_toolchain(),
    fragments = ["cpp"],
)
