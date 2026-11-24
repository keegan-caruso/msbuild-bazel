"""Qualification-only packed runtime; extraction is private to each invocation."""

load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo")

def _packed_runtime(ctx):
    runtime = ctx.attr.runtime[MSBuildRuntimeInfo]
    output = ctx.actions.declare_directory(ctx.label.name + ".runtime")
    launcher = ctx.actions.declare_file(ctx.label.name + ".launcher")
    ctx.actions.write(launcher, """#!/usr/bin/env python3
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile

root = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="msbuild-packed-", dir=os.environ.get("TEST_TMPDIR") or os.environ.get("TMPDIR") or "/tmp") as temporary:
    with tarfile.open(root / "runtime.tar.zst", "r:zst") as archive:
        archive.extractall(temporary, filter="data")
    environment = os.environ.copy()
    environment["DOTNET_HOST_PATH"] = str(Path(temporary) / %s)
    environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
    for name in ["DOTNET_ROOT", "DOTNET_ROOT_X64", "DOTNET_ROOT_X86", "DOTNET_ROOT_ARM", "DOTNET_ROOT_ARM64"]:
        environment[name] = temporary
    %s
    # Popen inherits stdin and restores the child's ordinary signal dispositions.
    child = subprocess.Popen([environment["DOTNET_HOST_PATH"], *sys.argv[1:]], env=environment)
    def forward(signum, frame):
        child.send_signal(signum)
    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)
    status = child.wait()
    sys.exit(status if status >= 0 else 128 - status)
""" % (json.encode(runtime.entry_point), 'environment["CORE_ROOT"] = temporary' if runtime.launch_mode == "corerun" else 'environment.pop("CORE_ROOT", None)'), is_executable = True)
    ctx.actions.run_shell(
        inputs = depset([launcher], transitive = [runtime.files]),
        outputs = [output],
        arguments = [runtime.directory.path, output.path, launcher.path],
        command = """set -eu
mkdir -p "$2"
python3 - "$1" "$2/runtime.tar.zst" <<'PYTHON'
import sys
import tarfile

def normalize(entry):
    entry.uid = entry.gid = entry.mtime = 0
    entry.uname = entry.gname = ""
    return entry

with tarfile.open(sys.argv[2], "w:zst", level=9, dereference=True) as archive:
    archive.add(sys.argv[1], arcname=".", filter=normalize)
PYTHON
cp "$3" "$2/launch"
chmod +x "$2/launch"
""",
        mnemonic = "SourceSdkPackRuntime",
    )
    return [DefaultInfo(files = depset([output])), MSBuildRuntimeInfo(
        directory = output,
        entry_point = "launch",
        launch_mode = runtime.launch_mode,
        runtime_identifier = runtime.runtime_identifier,
        version = runtime.version,
        environment = runtime.environment,
        files = depset([output]),
    )]

packed_runtime = rule(
    implementation = _packed_runtime,
    attrs = {"runtime": attr.label(providers = [MSBuildRuntimeInfo], mandatory = True)},
)
