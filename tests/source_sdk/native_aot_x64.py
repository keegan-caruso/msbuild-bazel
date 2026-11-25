"""Bounded native Linux x64 graph NativeAOT Publish with source SDK and LLVM 18.

Consumes hash-verified SDK/native archives; never registers a host-path SDK.
The native archive must come from assemble-native-toolchain.py --architecture=x64.
"""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--sdk", type=Path, required=True)
    p.add_argument("--sdk-sha256", required=True)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--native-sha256", required=True)
    p.add_argument("--prepare-only", action="store_true")
    a = p.parse_args()
    for path, expected in [(a.sdk, a.sdk_sha256), (a.native, a.native_sha256)]:
        if digest(path) != expected:
            raise ValueError("Archive SHA256 mismatch: " + str(path))
    folder = a.directory.resolve()
    w = folder / "workspace"
    w.mkdir(parents=True, exist_ok=False)
    for source, name, expected in [
        (a.sdk, "sdk.tar.gz", a.sdk_sha256),
        (a.native, "native.tar", a.native_sha256),
    ]:
        destination = w / name
        shutil.copyfile(source, destination)
        if digest(destination) != expected:
            raise ValueError("Workspace archive SHA256 mismatch: " + str(destination))
    shutil.copyfile(
        ROOT / "tests/source_sdk/source_action.bzl", w / "source_action.bzl"
    )
    fixtures = Path(__file__).with_suffix("")

    def put(name, text):
        (w / name).write_text(text)

    put(
        "MODULE.bazel",
        'module(name="native_aot_x64")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='
        + json.dumps(str(ROOT))
        + ')\nregister_toolchains("//:produced_registered","//:produced_runtime_registered")\n',
    )
    shutil.copyfile(fixtures / "native.bzl", w / "native.bzl")
    for name in ["clang", "objcopy"]:
        shutil.copyfile(fixtures / name, w / name)
    shutil.copyfile(fixtures / "Hello.csproj", w / "Hello.csproj")
    shutil.copyfile(fixtures / "Program.cs", w / "Program.cs")
    put(
        "contract.json",
        json.dumps(
            dict(
                Version=1,
                Entry="Hello.csproj",
                SdkVersion="10.0.100",
                Properties={"Configuration": "Release"},
                SharedInputs=[],
                ToolProperties={
                    "CppCompilerAndLinker": ".graph-tools/0/clang",
                },
                Projects={
                    "Hello.csproj": dict(
                        Inputs=["Hello.csproj", "Program.cs"],
                        OutputDirectories=[
                            "bin/Release/net10.0/ubuntu.26.04-x64",
                            "obj/Release/net10.0/ubuntu.26.04-x64",
                            "bin/publish",
                        ],
                    )
                },
            )
        ),
    )
    shutil.copyfile(fixtures / "BUILD.template", w / "BUILD.bazel")
    report = {
        "sdkSha256": a.sdk_sha256,
        "nativeSha256": a.native_sha256,
        "rulesRevision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
    }
    (folder / "inputs.json").write_text(json.dumps(report, indent=2) + "\n")
    if a.prepare_only:
        return
    if (platform.system(), platform.machine()) != ("Linux", "x86_64"):
        raise ValueError("Run on native Linux x64")
    command = [
        str(ROOT / "scripts/bazel-launcher.sh"),
        "--batch",
        "--host_jvm_args=-Xmx1024m",
        "--output_base=" + str(folder / "base"),
        "--ignore_all_rc_files",
        "build",
        "//:published",
        "//:binary",
        "--jobs=2",
        "--local_test_jobs=1",
        "--lockfile_mode=off",
        "--disk_cache=",
        "--remote_cache=",
        "--execution_log_json_file=" + str(folder / "execution.json"),
    ]
    with (folder / "publish.log").open("w") as log:
        subprocess.run(
            command,
            cwd=w,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=True,
        )
    log = (folder / "publish.log").read_text()
    if "clang version 18.1.8" not in log or "LLD 18.1.8" not in log:
        raise ValueError("No evidence of pinned Clang 18.1.8 invocation")
    layout = w / "bazel-bin/published.layout"
    independent = folder / "independent"
    shutil.copytree(layout, independent, symlinks=False)
    binary = independent / "Hello"
    data = binary.read_bytes()
    if data[:4] != b"\x7fELF" or int.from_bytes(data[18:20], "little") != 62:
        raise ValueError("Expected ELF x86-64")
    with tarfile.open(folder / "published.tar.gz", "w:gz") as package:
        package.add(independent, arcname="published")
    extracted = folder / "extracted"
    with tarfile.open(folder / "published.tar.gz") as package:
        package.extractall(extracted, filter="data")
    if any(
        (extracted / "published" / name).exists()
        for name in ["Hello.dll", "Hello.runtimeconfig.json", "libcoreclr.so"]
    ):
        raise ValueError("Published output includes managed-host companions")
    standalone = folder / "standalone"
    standalone.mkdir()
    shutil.copy2(extracted / "published/Hello", standalone / "Hello")
    binary = standalone / "Hello"
    run = subprocess.run(
        [binary],
        cwd=standalone,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(independent),
            "DOTNET_ROOT": "/nonexistent",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    if run.stdout.splitlines() != [
        "SOURCE_SDK_NATIVE_AOT_X64",
        "X64",
        "DYNAMIC_CODE=False",
    ]:
        raise ValueError(run.stdout)
    report.update(
        binarySha256=digest(binary),
        packageSha256=digest(folder / "published.tar.gz"),
        output=run.stdout,
        elfMachine=62,
        standaloneFiles=sorted(path.name for path in standalone.iterdir()),
        dynamicCodeSupported=False,
        nativeCompilerEvidence=[
            line.strip()
            for line in log.splitlines()
            if "clang version 18.1.8" in line or "LLD 18.1.8" in line
        ],
        command=command,
    )
    (folder / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
