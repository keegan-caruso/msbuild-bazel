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


def build_file(omit_compiler=False, declared_toolchain=False, omit_native_compiler=False, toolchain_sha256=None, native_packages=None, bad_native_package=False, selected_native_toolchain=False, remote_execution=False):
    names = []
    lines = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_generate", "msbuild_nuget_package", "msbuild_package_lock")']
    for index, (package_id, (digest, content_hash)) in enumerate(PACKAGES.items()):
        name = f"pkg{index}"
        lines.append(f'msbuild_nuget_package(name="{name}", package_id="{package_id}", version="{VERSION}", archive="packages/{package_id}.{VERSION}.nupkg", archive_sha256="{digest}", content_hash="{content_hash}")')
        if not omit_compiler or package_id != "microsoft.dotnet.ilcompiler":
            names.append(":" + name)
    lines.append(f'msbuild_package_lock(name="lock", packages={json.dumps(names)})')
    native = 'use_native_toolchain=True' if selected_native_toolchain else 'native_toolchain=":native_toolchain"' if declared_toolchain else 'local_native_tools=True'
    lines.append('msbuild_generate(name="aot", executable=True, project="Hello.csproj", srcs=["Program.cs"], target_framework="net10.0", targets=["ExportAot"], outputs=["Hello"], output_properties={"NativeBinaryOutput":"Hello"}, package_lock=":lock", build_deps=' + json.dumps(names) + ', ' + native + (', allow_remote_execution=True' if remote_execution else '') + ')')
    if declared_toolchain:
        if native_packages is not None:
            lines[0] = lines[0].replace('"msbuild_generate",', '"msbuild_generate", "msbuild_native_toolchain_packages", "msbuild_native_toolchain",')
            package_hashes = {"packages/" + package["name"] + ".deb": ("0" * 64 if bad_native_package and index == 0 else package["sha256"]) for index, package in enumerate(native_packages)}
            lines.append('msbuild_native_toolchain_packages(name="native_toolchain", manifest="native-aot-files.manifest", packages=' + json.dumps(package_hashes) + ')')
            if selected_native_toolchain:
                lines.append('msbuild_native_toolchain(name="native_binding", root=":native_toolchain")')
                lines.append('toolchain(name="native_registered", toolchain=":native_binding", toolchain_type="@rules_msbuild//msbuild:native_toolchain_type", exec_compatible_with=["@platforms//os:linux", "@platforms//cpu:aarch64"], target_compatible_with=["@platforms//os:linux", "@platforms//cpu:aarch64"])')
        elif toolchain_sha256:
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
    parser.add_argument("--native-package-directory", type=Path, help="Use pinned Ubuntu .deb payloads as a Bazel-built native toolchain")
    parser.add_argument("--selected-native-toolchain", action="store_true", help="Select the package-built tree through Bazel toolchain resolution")
    parser.add_argument("--remote-executor", help="Qualify actual remote AOT generation on an SDK-free Linux ARM64 executor")
    args = parser.parse_args()
    if bool(args.toolchain_archive) != bool(args.toolchain_sha256):
        parser.error("--toolchain-archive and --toolchain-sha256 must be supplied together")
    if args.native_package_directory and (args.toolchain_archive or args.declared_toolchain):
        parser.error("Choose one native toolchain source")
    if args.selected_native_toolchain and not args.native_package_directory:
        parser.error("--selected-native-toolchain requires --native-package-directory")
    if args.remote_executor and not args.selected_native_toolchain:
        parser.error("--remote-executor requires --selected-native-toolchain")
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        parser.error("This first Native AOT fixture qualifies Linux ARM64 only")
    folder = args.directory.resolve()
    workspace = folder / "source"
    workspace.mkdir(parents=True, exist_ok=False)
    module_file = workspace / "MODULE.bazel"
    module_text = 'module(name="native_aot_fixture")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n' + ('bazel_dep(name="platforms",version="1.0.0")\n' if args.selected_native_toolchain else '') + sdk_declarations() + ('register_toolchains("//:native_registered")\n' if args.selected_native_toolchain else '')
    write(module_file, module_text)
    write(workspace / "Hello.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><RuntimeIdentifier>linux-arm64</RuntimeIdentifier><PublishAot>true</PublishAot><SelfContained>true</SelfContained><PublishDir>$(BaseIntermediateOutputPath)publish/</PublishDir></PropertyGroup><Target Name="ExportAot" DependsOnTargets="Publish"><Copy SourceFiles="$(PublishDir)Hello" DestinationFiles="$(NativeBinaryOutput)" /></Target></Project>')
    write(workspace / "Program.cs", 'System.Console.WriteLine("NATIVE_AOT_INITIAL");\n')
    for package_id, (digest, _) in PACKAGES.items():
        package_archive(workspace, package_id, digest, args.package_cache)
    native_packages = None
    if args.native_package_directory:
        native_packages = json.loads((ROOT / "tests/explicit_msbuild/native_aot_packages.lock.json").read_text())["packages"]
        shutil.copyfile(ROOT / "tests/explicit_msbuild/native_aot_files.manifest", workspace / "native-aot-files.manifest")
        for package in native_packages:
            source = args.native_package_directory / (package["name"] + ".deb")
            package_archive_path = workspace / "packages" / source.name
            package_archive_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, package_archive_path)
            actual = hashlib.sha256(package_archive_path.read_bytes()).hexdigest()
            if actual != package["sha256"]:
                raise ValueError("Unexpected native package digest for " + package["name"] + ": " + actual)
    declared_toolchain = args.declared_toolchain or bool(args.toolchain_archive) or native_packages is not None
    if args.toolchain_archive:
        shutil.copyfile(args.toolchain_archive, workspace / "native-toolchain.tar.gz")
    elif declared_toolchain:
        write(workspace / "native_toolchain.bzl", (ROOT / "tests/explicit_msbuild/native_toolchain.bzl").read_text())
    def build_declaration(**kwargs):
        return build_file(declared_toolchain=declared_toolchain, toolchain_sha256=args.toolchain_sha256, native_packages=native_packages, selected_native_toolchain=args.selected_native_toolchain, remote_execution=bool(args.remote_executor), **kwargs)

    write(workspace / "BUILD.bazel", build_declaration())
    bazel = [os.environ["RULES_MSBUILD_BAZEL"], "--output_base=" + str(folder / "base"), "--ignore_all_rc_files"]

    def build(case, success=True):
        command = bazel + ["build", "//:aot", "--jobs=2", "--lockfile_mode=off"]
        if args.remote_executor:
            command += [
                "--disk_cache=", "--remote_executor=" + args.remote_executor,
                "--remote_cache=" + args.remote_executor,
                "--remote_instance_name=native-aot/" + folder.name,
                "--noremote_local_fallback", "--spawn_strategy=remote",
                "--strategy=MSBuildGenerate=remote",
                "--strategy=MSBuildNativeToolchainPackages=local",
                "--remote_accept_cached=false",
                "--remote_upload_local_results=false", "--remote_download_outputs=all",
                "--remote_default_exec_properties=ISA=aarch64",
                "--remote_default_exec_properties=OSFamily=linux",
                "--remote_default_exec_properties=rules_msbuild_image=47a9e2fed018-sdk-removed",
                "--execution_log_json_file=" + str(folder / (case + ".execution.json")),
            ]
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, errors="replace", timeout=900)
        output = result.stdout + result.stderr
        write(folder / (case + ".log"), output)
        assert (result.returncode == 0) == success, output[-7000:]
        if args.remote_executor and success and case in ("initial", "body-edit"):
            execution = (folder / (case + ".execution.json")).read_text()
            decoder = json.JSONDecoder()
            rows = []
            while execution.strip():
                row, end = decoder.raw_decode(execution.lstrip())
                execution = execution.lstrip()[end:]
                if row.get("mnemonic") == "MSBuildGenerate":
                    rows.append(row)
            assert len(rows) == 1 and rows[0]["runner"] == "remote" and not rows[0].get("cacheHit"), rows
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
        write(workspace / "BUILD.bazel", build_declaration(omit_compiler=True))
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
        if native_packages is not None:
            write(workspace / "BUILD.bazel", build_declaration(bad_native_package=True))
            bad_package = build("bad-native-package-hash", success=False)
            assert "Native package differs from locked SHA-256" in bad_package, bad_package[-7000:]
        if args.selected_native_toolchain:
            write(workspace / "BUILD.bazel", build_declaration())
            write(module_file, module_text.replace('register_toolchains("//:native_registered")\n', ''))
            missing_native = build("missing-selected-native-toolchain", success=False)
            assert "No native toolchain matches this platform" in missing_native, missing_native[-7000:]
            write(module_file, module_text)
        write(folder / "report.json", json.dumps({"platform": "linux-arm64", "sdk": "10.0.400", "aotPackages": VERSION, "declaredToolchain": declared_toolchain, "selectedNativeToolchain": args.selected_native_toolchain, "remoteExecution": bool(args.remote_executor), "toolchainArchiveSha256": args.toolchain_sha256, "nativePackageCount": len(native_packages) if native_packages is not None else 0, "initialSha256": first_hash, "bodyEditSha256": second_hash, "missingCompilerRejected": True, "missingNativeCompilerRejected": args.declared_toolchain and not args.toolchain_archive, "missingSelectedNativeToolchainRejected": args.selected_native_toolchain, "badArchiveRejected": bool(args.toolchain_archive), "badNativePackageRejected": native_packages is not None}, indent=2) + "\n")
    finally:
        write(module_file, module_text)
        write(workspace / "BUILD.bazel", build_declaration())
        subprocess.run(bazel + ["shutdown"], cwd=workspace, check=True)


if __name__ == "__main__":
    main()
