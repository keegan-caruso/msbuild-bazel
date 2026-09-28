"""Qualify a Linux ARM64 Native AOT publish with locked Bazel package inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixture_sdk import sdk_declarations


ROOT = Path(__file__).resolve().parents[2]
VERSION = "10.0.11"
# SHA-256 is over the downloaded archive; the NuGet content hash is over the
# same bytes and is checked again by msbuild_nuget_package during extraction.
PACKAGES = {
    "microsoft.aspnetcore.app.runtime.linux-arm64": ("0953a9b241bb8860489507344fa33015b62cd7899c2676a188c186fb40aa29bf", "gDHFTYuhJV+0Kg+lmwS6CZWqoAc3daRCktKmvZ4PqjLD9h9ZNNYKZBhP6Y6hnaq1V4T4qN7M93dVwZtUdRpPeA=="),
    "microsoft.dotnet.ilcompiler": ("da108b2e633101c25b0df6a7a0c6023614f24b92f4bfb0eb2c0814e678a0c871", "R21pKwl2STwYU17wo8b8pbY+xKw0LYaNMi0wn09XoVs6lSK2vnjuV2CTf1zJ0a8Ew+iwe7T0tTmi5N3lW7DE1A=="),
    "microsoft.net.illink.tasks": ("28ee7ccf5c4bdfe67823c8e0ea62232174f61e224d77e7c6ef5caa1413ac0a76", "hMVB326ViZa64sqR9bxmf4oB41LMuaTrGRfihXZw3dylFRFfZPutLwJrKZmdisSvBcNM6kfuY7vtj9vdR9IbuA=="),
    "microsoft.netcore.app.runtime.linux-arm64": ("72228f5be7e71d8db5cd9df6571e51a1c6a8d16f329343393aa85a1bd6673d1a", "2lKSs6dpNXSgX9Wuj2iasd52IPUL/VgP7YLb4CB9OnytsjFfVkQEPIAfIe9Dy2ke3Lsm/OotZVNjJAJcnak5CA=="),
    "microsoft.netcore.app.runtime.nativeaot.linux-arm64": ("f1a10e408eeb8100c2f23be9bcda1db54ce59a7e9e1110c2ce6d94461dbd420f", "T6z16bUu2om8Qes02PTkqmuGgUlb10EdL77cFOAzno8PI02nl6Oa+cEmTXgXkHLv9Tw9ALRGytgz0aaQeerVWQ=="),
    "runtime.linux-arm64.microsoft.dotnet.ilcompiler": ("2b05c92219b986c387612cefe179cb8a9157974a0e75776f9d33684367ce1e4a", "EtTwxmg9PfefrrT73nNntoxnbHN7h4X6LlIm/ZJq0T/9J4uf9MnlDzAru+HwNof+f6hOvI/kwwXxM+WDPJ41iw=="),
}


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def package_archive(workspace, package_id, digest, cache):
    name = f"{package_id}.{VERSION}.nupkg"
    archive = workspace / "packages" / name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if cache:
        shutil.copyfile(cache / package_id / VERSION / name, archive)
    else:
        url = f"https://api.nuget.org/v3-flatcontainer/{package_id}/{VERSION}/{name}"
        with urlopen(url, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != digest:
        raise ValueError(f"Unexpected NuGet archive digest for {name}: {actual}")
    return archive


def build_file(omit_compiler=False, declared_toolchain=False, omit_native_compiler=False, toolchain_sha256=None):
    names = []
    lines = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_generate", "msbuild_nuget_package", "msbuild_package_lock")']
    for index, (package_id, (digest, content_hash)) in enumerate(PACKAGES.items()):
        name = f"pkg{index}"
        lines.append(f'msbuild_nuget_package(name="{name}", package_id="{package_id}", version="{VERSION}", archive="packages/{package_id}.{VERSION}.nupkg", archive_sha256="{digest}", content_hash="{content_hash}")')
        if not omit_compiler or package_id != "microsoft.dotnet.ilcompiler":
            names.append(":" + name)
    lines.append(f'msbuild_package_lock(name="lock", packages={json.dumps(names)})')
    native = 'native_toolchain=":native_toolchain"' if declared_toolchain else 'local_native_tools=True'
    lines.append('msbuild_generate(name="aot", executable=True, project="Hello.csproj", srcs=["Program.cs"], target_framework="net10.0", targets=["ExportAot"], outputs=["Hello"], output_properties={"NativeBinaryOutput":"Hello"}, package_lock=":lock", build_deps=' + json.dumps(names) + ', ' + native + ')')
    if declared_toolchain:
        if toolchain_sha256:
            lines[0] = lines[0].replace('"msbuild_generate",', '"msbuild_generate", "msbuild_native_toolchain_archive",')
            lines.append('msbuild_native_toolchain_archive(name="native_toolchain", archive="native-toolchain.tar.gz", archive_sha256="' + toolchain_sha256 + '")')
        else:
            lines.insert(1, 'load(":native_toolchain.bzl", "native_toolchain_snapshot")')
            lines.append('native_toolchain_snapshot(name="native_toolchain", omit_compiler=' + str(omit_native_compiler) + ')')
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--package-cache", type=Path, help="Previously downloaded NuGet package root")
    parser.add_argument("--declared-toolchain", action="store_true", help="Snapshot the host native toolchain as a declared tree input")
    parser.add_argument("--toolchain-archive", type=Path, help="Use a locked tar.gz archive rather than snapshotting native tools from the host")
    parser.add_argument("--toolchain-sha256", help="Expected SHA-256 of --toolchain-archive")
    args = parser.parse_args()
    if bool(args.toolchain_archive) != bool(args.toolchain_sha256):
        parser.error("--toolchain-archive and --toolchain-sha256 must be supplied together")
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        parser.error("This first Native AOT fixture qualifies Linux ARM64 only")
    folder = args.directory.resolve()
    workspace = folder / "source"
    workspace.mkdir(parents=True, exist_ok=False)
    write(workspace / "MODULE.bazel", 'module(name="native_aot_fixture")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n' + sdk_declarations())
    write(workspace / "Hello.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><RuntimeIdentifier>linux-arm64</RuntimeIdentifier><PublishAot>true</PublishAot><SelfContained>true</SelfContained><PublishDir>$(BaseIntermediateOutputPath)publish/</PublishDir></PropertyGroup><Target Name="ExportAot" DependsOnTargets="Publish"><Copy SourceFiles="$(PublishDir)Hello" DestinationFiles="$(NativeBinaryOutput)" /></Target></Project>')
    write(workspace / "Program.cs", 'System.Console.WriteLine("NATIVE_AOT_INITIAL");\n')
    for package_id, (digest, _) in PACKAGES.items():
        package_archive(workspace, package_id, digest, args.package_cache)
    declared_toolchain = args.declared_toolchain or bool(args.toolchain_archive)
    if args.toolchain_archive:
        shutil.copyfile(args.toolchain_archive, workspace / "native-toolchain.tar.gz")
    elif declared_toolchain:
        write(workspace / "native_toolchain.bzl", (ROOT / "tests/explicit_msbuild/native_toolchain.bzl").read_text())
    write(workspace / "BUILD.bazel", build_file(declared_toolchain=declared_toolchain, toolchain_sha256=args.toolchain_sha256))
    bazel = [os.environ["RULES_MSBUILD_BAZEL"], "--output_base=" + str(folder / "base"), "--ignore_all_rc_files"]

    def build(case, success=True):
        result = subprocess.run(bazel + ["build", "//:aot", "--jobs=2", "--lockfile_mode=off"], cwd=workspace, capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        write(folder / (case + ".log"), output)
        assert (result.returncode == 0) == success, output[-7000:]
        return output

    try:
        build("initial")
        binary = workspace / "bazel-bin/aot.generated/Hello"
        data = binary.read_bytes()
        assert data[:4] == b"\x7fELF" and int.from_bytes(data[18:20], "little") == 183, "Expected an ARM64 ELF binary"
        first_hash = hashlib.sha256(data).hexdigest()
        assert subprocess.check_output([binary], text=True).strip() == "NATIVE_AOT_INITIAL"
        write(workspace / "Program.cs", 'System.Console.WriteLine("NATIVE_AOT_EDIT");\n')
        build("body-edit")
        second_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
        assert first_hash != second_hash
        assert subprocess.check_output([binary], text=True).strip() == "NATIVE_AOT_EDIT"
        write(workspace / "BUILD.bazel", build_file(omit_compiler=True, declared_toolchain=declared_toolchain, toolchain_sha256=args.toolchain_sha256))
        failure = build("missing-compiler", success=False)
        assert "Microsoft.DotNet.ILCompiler" in failure and ("NU1100" in failure or "NU1101" in failure), failure[-7000:]
        if args.declared_toolchain and not args.toolchain_archive:
            write(workspace / "BUILD.bazel", build_file(declared_toolchain=True, omit_native_compiler=True))
            missing_native = build("missing-native-compiler", success=False)
            assert "Platform linker ('clang' or 'gcc') not found in PATH" in missing_native, missing_native[-7000:]
        if args.toolchain_archive:
            write(workspace / "BUILD.bazel", build_file(declared_toolchain=True, toolchain_sha256="0" * 64))
            bad_archive = build("bad-toolchain-hash", success=False)
            assert "Native toolchain archive differs from locked SHA-256" in bad_archive, bad_archive[-7000:]
        write(folder / "report.json", json.dumps({"platform": "linux-arm64", "sdk": "10.0.400", "aotPackages": VERSION, "declaredToolchain": declared_toolchain, "toolchainArchiveSha256": args.toolchain_sha256, "initialSha256": first_hash, "bodyEditSha256": second_hash, "missingCompilerRejected": True, "missingNativeCompilerRejected": args.declared_toolchain and not args.toolchain_archive, "badArchiveRejected": bool(args.toolchain_archive)}, indent=2) + "\n")
    finally:
        write(workspace / "BUILD.bazel", build_file(declared_toolchain=declared_toolchain, toolchain_sha256=args.toolchain_sha256))
        subprocess.run(bazel + ["shutdown"], cwd=workspace, check=True)


if __name__ == "__main__":
    main()
